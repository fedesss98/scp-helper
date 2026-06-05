import logging

import httpx
from django.core.management.base import BaseCommand
from django.utils import timezone

from races.models import Race
from races.scraper import RaceScraper
from races.sync import scrape_and_sync_calendar, scrape_and_sync_program, scrape_and_sync_results

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Scrape race calendar, programs, and results into the Django database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--season",
            type=int,
            default=timezone.localdate().year,
            help="FIC season/year to scrape. Defaults to the current local year.",
        )
        parser.add_argument(
            "--skip-program",
            action="store_true",
            help="Only sync calendar and results; do not fetch race programs.",
        )
        parser.add_argument(
            "--skip-results",
            action="store_true",
            help="Only sync calendar and programs; do not fetch race results.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Fetch program/results for all synced races, including past races.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit the number of races hydrated after calendar sync.",
        )

    def handle(self, *args, **options):
        season = options["season"]
        today = timezone.localdate()

        with RaceScraper() as scraper:
            self.stdout.write(f"Scraping race calendar for season {season}...")
            synced_races = scrape_and_sync_calendar(scraper, season=season)
            self.stdout.write(self.style.SUCCESS(f"Synced {len(synced_races)} race calendar records."))

            queryset = Race.objects.filter(external_id__in=[race.external_id for race in synced_races])
            if not options["all"]:
                queryset = queryset.filter(date__gte=today)
            queryset = queryset.order_by("date", "external_id")
            if options["limit"]:
                queryset = queryset[: options["limit"]]

            program_count = 0
            result_count = 0
            new_result_count = 0

            for race in queryset:
                self.stdout.write(f"Hydrating {race.external_id} - {race.name or 'Unnamed race'}")

                if not options["skip_program"]:
                    try:
                        synced_program = scrape_and_sync_program(scraper, race)
                    except httpx.HTTPError as exc:
                        logger.warning("Program scrape failed for %s: %s", race.external_id, exc)
                        self.stderr.write(f"  Program failed: {exc}")
                    else:
                        if synced_program:
                            program_count += 1

                if not options["skip_results"]:
                    try:
                        new_results, synced_results = scrape_and_sync_results(scraper, race)
                    except httpx.HTTPError as exc:
                        logger.warning("Result scrape failed for %s: %s", race.external_id, exc)
                        self.stderr.write(f"  Results failed: {exc}")
                    else:
                        result_count += synced_results
                        new_result_count += len(new_results)

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"Programs synced: {program_count}. "
                f"Results synced: {result_count}. "
                f"New results: {new_result_count}."
            )
        )

