from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Race, RaceSubscription
from .scraper import normalize_club_name


def is_admin(user):
    return user.is_staff or user.is_superuser


def _club_key(value):
    return normalize_club_name(value).casefold()


def _entry_matches_club(entry, club_name):
    return _club_key(entry.get("club")) == _club_key(club_name)


def _prepare_program_races(program_races, club_name):
    prepared = []
    for program_race in program_races:
        race_copy = dict(program_race)
        entries = []
        has_target_club = False
        for entry in program_race.get("entries") or []:
            entry_copy = dict(entry)
            is_target_club = _entry_matches_club(entry_copy, club_name)
            entry_copy["is_target_club"] = is_target_club
            has_target_club = has_target_club or is_target_club
            entries.append(entry_copy)
        race_copy["entries"] = entries
        race_copy["has_target_club"] = has_target_club
        prepared.append(race_copy)
    return prepared


@login_required
def race_calendar(request):
    today = timezone.localdate()
    races = list(
        Race.objects.filter(Q(date__gte=today) | Q(date__isnull=True))
        .order_by("date", "name", "external_id")
    )
    subscribed_ids = set(
        RaceSubscription.objects.filter(user=request.user).values_list("race_id", flat=True)
    )
    for race in races:
        race.is_subscribed = race.id in subscribed_ids

    return render(
        request,
        "races/calendar.html",
        {
            "races": races,
            "today": today,
            "is_admin": is_admin(request.user),
        },
    )


@login_required
def race_detail(request, external_id):
    race = get_object_or_404(Race, external_id=external_id)
    is_subscribed = RaceSubscription.objects.filter(user=request.user, race=race).exists()
    results = race.results.all()
    program_payload = race.program_payload or {}
    club_name = getattr(settings, "RACE_CLUB_NAME", "PALERMO SC")
    club_short_name = getattr(settings, "RACE_CLUB_SHORT_NAME", "SCP")
    active_program_view = request.GET.get("program", "scp")
    if active_program_view not in {"scp", "full"}:
        active_program_view = "scp"

    all_program_races = _prepare_program_races(program_payload.get("races") or [], club_name)
    scp_program_races = [program_race for program_race in all_program_races if program_race["has_target_club"]]
    displayed_program_races = all_program_races if active_program_view == "full" else scp_program_races

    return render(
        request,
        "races/detail.html",
        {
            "race": race,
            "is_subscribed": is_subscribed,
            "program": program_payload,
            "program_races": displayed_program_races,
            "active_program_view": active_program_view,
            "full_program_count": len(all_program_races),
            "scp_program_count": len(scp_program_races),
            "race_club_name": club_name,
            "race_club_short_name": club_short_name,
            "results": results,
            "is_admin": is_admin(request.user),
        },
    )


@login_required
@require_POST
def subscribe_race(request, race_id):
    race = get_object_or_404(Race, pk=race_id)
    _subscription, created = RaceSubscription.objects.get_or_create(user=request.user, race=race)
    if created:
        messages.success(request, f"Iscrizione attivata per {race.name or race.external_id}.")
    else:
        messages.info(request, f"Eri gia iscritto a {race.name or race.external_id}.")
    return _redirect_after_subscription(request, race)


@login_required
@require_POST
def unsubscribe_race(request, race_id):
    race = get_object_or_404(Race, pk=race_id)
    deleted, _ = RaceSubscription.objects.filter(user=request.user, race=race).delete()
    if deleted:
        messages.success(request, f"Iscrizione rimossa per {race.name or race.external_id}.")
    else:
        messages.info(request, f"Non eri iscritto a {race.name or race.external_id}.")
    return _redirect_after_subscription(request, race)


def _redirect_after_subscription(request, race):
    next_url = request.POST.get("next")
    if next_url in {reverse("race_calendar"), reverse("race_detail", args=[race.external_id])}:
        return redirect(next_url)
    return redirect("race_calendar")
