import logging
from typing import Iterable

import requests
from django.conf import settings

from races.models import Race, RaceResult, RaceSubscription
from races.scraper import normalize_club_name

logger = logging.getLogger(__name__)


def send_telegram(chat_id, message):
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN is not configured; skipping Telegram send.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Telegram send failed for chat_id=%s: %s", chat_id, exc)
        return False
    return True


def notify_new_results(race: Race, new_results: Iterable[RaceResult]) -> int:
    club_name = getattr(settings, "RACE_CLUB_NAME", "PALERMO SC")
    results = [
        result
        for result in new_results
        if normalize_club_name(result.club).casefold() == normalize_club_name(club_name).casefold()
    ]
    if not results:
        return 0

    message = format_results_message(race, results, club_name)
    sent_count = 0

    subscriptions = RaceSubscription.objects.filter(race=race).select_related("user__profile")
    for subscription in subscriptions:
        profile = getattr(subscription.user, "profile", None)
        chat_id = getattr(profile, "telegram_chat_id", "") if profile else ""
        if not chat_id:
            continue
        if send_telegram(chat_id, message):
            sent_count += 1

    return sent_count


def format_results_message(race: Race, results: list[RaceResult], club_name: str | None = None) -> str:
    title = race.name or race.external_id
    club_label = club_name or getattr(settings, "RACE_CLUB_NAME", "PALERMO SC")
    lines = [f"Nuovi risultati {club_label} per {title} ({race.external_id})"]

    for result in results[:20]:
        athletes = ", ".join(result.athletes or [])
        position = result.position if result.position is not None else "-"
        event = result.event or "Evento"
        club = result.club or "-"
        finish_time = result.finish_time or "N/D"
        lines.append(
            f"GARA {result.race_number or '-'} - {event}: "
            f"{club} pos. {position}, tempo {finish_time}"
        )
        if athletes:
            lines.append(f"  Atleti: {athletes}")

    if len(results) > 20:
        lines.append(f"... e altri {len(results) - 20} risultati.")

    return "\n".join(lines)
