from __future__ import annotations

from datetime import datetime
import hashlib
import json
import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Race, RaceResult
from .scraper import DataNotAvailableError, RaceScraper

logger = logging.getLogger(__name__)


def parse_calendar_date(value: str | None) -> datetime.date | None:
    if not value:
        return None

    raw = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def build_result_external_id(reg_id: str, source: str, race_data: dict[str, Any], finisher: dict[str, Any]) -> str:
    race_number = race_data.get("race_number")
    bib = finisher.get("bib")
    stable_payload = {
        "reg_id": reg_id,
        "source": source or "",
        "race_number": race_number,
        "event": race_data.get("event") or "",
        "phase": race_data.get("phase") or "",
        "bib": bib,
        "lane": finisher.get("lane"),
        "club": finisher.get("club") or "",
        "athletes": finisher.get("athletes") or [],
    }
    digest = hashlib.sha1(
        json.dumps(stable_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    bib_token = str(bib) if bib is not None else "no-bib"
    return f"{reg_id}:{race_number or 'na'}:{bib_token}:{digest}"


def sync_race_from_calendar_entry(entry: dict[str, Any], *, scraped_at=None) -> tuple[Race, bool]:
    scraped_at = scraped_at or timezone.now()
    external_id = _clean_text(entry.get("reg_id") or entry.get("external_id"))
    if not external_id:
        raise ValueError("Race calendar entry is missing reg_id/external_id")

    defaults = {
        "name": _clean_text(entry.get("name")),
        "location": _clean_text(entry.get("location")),
        "date": parse_calendar_date(entry.get("date")),
        "category": _clean_text(entry.get("category")),
        "url": _clean_text(entry.get("url")),
        "last_scraped": scraped_at,
    }
    return Race.objects.update_or_create(external_id=external_id, defaults=defaults)


def sync_calendar_payload(payload: dict[str, Any], *, scraped_at=None) -> list[Race]:
    scraped_at = scraped_at or timezone.now()
    synced: list[Race] = []
    for entry in payload.get("races") or []:
        race, _created = sync_race_from_calendar_entry(entry, scraped_at=scraped_at)
        synced.append(race)
    return synced


def sync_program_payload(race: Race, payload: dict[str, Any], *, scraped_at=None) -> Race:
    scraped_at = scraped_at or timezone.now()
    race.program_payload = payload
    race.last_scraped = scraped_at
    race.save(update_fields=["program_payload", "last_scraped", "updated_at"])
    return race


def _result_defaults(
    race: Race,
    source: str,
    race_data: dict[str, Any],
    finisher: dict[str, Any],
) -> dict[str, Any]:
    athletes = finisher.get("athletes") or []
    if not isinstance(athletes, list):
        athletes = [str(athletes)]

    raw_data = {
        "race": race_data,
        "finisher": finisher,
    }

    return {
        "race": race,
        "source": source,
        "race_number": race_data.get("race_number"),
        "race_date_day": _clean_text(race_data.get("date_day")),
        "event": _clean_text(race_data.get("event")),
        "phase": _clean_text(race_data.get("phase")),
        "position": finisher.get("position"),
        "master_class": _clean_text(finisher.get("master_class")),
        "finish_time": _clean_text(finisher.get("time")),
        "lane": finisher.get("lane"),
        "bib": finisher.get("bib"),
        "club": _clean_text(finisher.get("club")),
        "athletes": athletes,
        "gap": _clean_text(finisher.get("gap")),
        "status": _clean_text(finisher.get("status")),
        "raw_data": raw_data,
    }


@transaction.atomic
def sync_results_payload(race: Race, payload: dict[str, Any], *, scraped_at=None) -> tuple[list[RaceResult], int]:
    scraped_at = scraped_at or timezone.now()
    new_results: list[RaceResult] = []
    synced_count = 0

    for race_data in payload.get("races") or []:
        source = _clean_text(race_data.get("source"))
        for finisher in race_data.get("finishers") or []:
            external_id = build_result_external_id(race.external_id, source, race_data, finisher)
            result, created = RaceResult.objects.update_or_create(
                external_id=external_id,
                defaults=_result_defaults(race, source, race_data, finisher),
            )
            synced_count += 1
            if created:
                new_results.append(result)

    race.last_scraped = scraped_at
    race.save(update_fields=["last_scraped", "updated_at"])
    return new_results, synced_count


def scrape_and_sync_calendar(scraper: RaceScraper, *, season: int | None = None) -> list[Race]:
    payload = scraper.get_calendar_payload(stagione=season)
    return sync_calendar_payload(payload)


def scrape_and_sync_program(scraper: RaceScraper, race: Race) -> Race | None:
    try:
        payload = scraper.get_program_payload(race.external_id)
    except DataNotAvailableError:
        logger.info("Program not available yet for race %s", race.external_id)
        return None
    sync_program_payload(race, payload)
    return race


def scrape_and_sync_results(scraper: RaceScraper, race: Race) -> tuple[list[RaceResult], int]:
    try:
        payload = scraper.get_results_payload(race.external_id)
    except DataNotAvailableError:
        logger.info("Results not available yet for race %s", race.external_id)
        return [], 0
    return sync_results_payload(race, payload)

