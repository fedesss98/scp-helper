"""Scraping utilities for canottaggioservice.org race data.

This module is deliberately framework-free. It keeps the request URLs,
encodings, and parsing rules from the old FastAPI service, but exposes plain
Python functions/classes that Django commands, views, and workers can call.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import time
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScraperConfig:
    base_url: str = os.getenv("FIC_BASE_URL", "https://canottaggioservice.canottaggio.net")
    user_agent: str = os.getenv("FIC_USER_AGENT", "Mozilla/5.0")
    timeout_s: float = float(os.getenv("FIC_TIMEOUT_S", "15"))
    calendar_request_delay_s: float = float(os.getenv("FIC_CALENDAR_REQUEST_DELAY_S", "0.5"))
    calendar_cache_ttl_s: int = int(os.getenv("FIC_CALENDAR_CACHE_TTL_S", "3600"))

    @property
    def headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent}


class DataNotAvailableError(Exception):
    """Raised when upstream data exists conceptually but is not published yet."""


def normalize_club_name(club: str | None) -> str:
    """Normalize names by removing trailing decorators like '(1)' or '(1 Misto)'."""
    if not club:
        return ""
    cleaned = re.sub(r"\s*\(\d+(?:\s+misto)?\)\s*$", "", club, flags=re.IGNORECASE)
    return " ".join(cleaned.strip().split())


def club_matches_team(club: str | None, team: str | None) -> bool:
    """Return True when club and team are exactly equal, case-insensitively."""
    club_key = normalize_club_name(club).casefold()
    team_key = normalize_club_name(team).casefold()
    if not club_key or not team_key:
        return False
    return team_key == club_key


def guest_club_matches_team(guest_clubs: dict[str, Any] | None, team: str | None) -> bool:
    """Return True when team appears in guest clubs mapping values."""
    team_key = normalize_club_name(team).casefold()
    if not team_key:
        return False
    for guest in (guest_clubs or {}).values():
        if normalize_club_name(str(guest)).casefold() == team_key:
            return True
    return False


def finisher_matches_team(finisher: dict[str, Any], team: str) -> bool:
    """Return True if team is the main club or appears as guest club."""
    return club_matches_team(finisher.get("club", ""), team) or guest_club_matches_team(
        finisher.get("guest_clubs"), team
    )


def extract_unique_clubs(payload: dict[str, Any]) -> list[str]:
    """Extract all unique normalized clubs from a regatta results payload."""
    clubs: set[str] = set()
    for race in payload.get("races") or []:
        for finisher in race.get("finishers") or []:
            club = normalize_club_name(finisher.get("club"))
            if club:
                clubs.add(club)
            guest_clubs = finisher.get("guest_clubs") or {}
            for guest_club in guest_clubs.values():
                normalized_guest = normalize_club_name(guest_club)
                if normalized_guest:
                    clubs.add(normalized_guest)
    return sorted(clubs)


def extract_unique_program_clubs(payload: dict[str, Any]) -> list[str]:
    """Extract unique clubs from program races/entries payload."""
    clubs_by_key: dict[str, str] = {}

    def add_club(raw_club: str | None) -> None:
        normalized = normalize_club_name(raw_club)
        if not normalized or normalized.casefold() == "da assegnare":
            return
        key = normalized.casefold()
        if key not in clubs_by_key:
            clubs_by_key[key] = normalized

    for race in payload.get("races") or []:
        for entry in race.get("entries") or []:
            add_club(entry.get("club"))
            guest_clubs = entry.get("guest_clubs") or {}
            for guest_club in guest_clubs.values():
                add_club(guest_club)

    return sorted(clubs_by_key.values())


class RaceScraper:
    """Business logic for regatta fetch and parse operations."""

    def __init__(self, config: ScraperConfig | None = None) -> None:
        self.config = config or ScraperConfig()
        self.base_url = self.config.base_url
        self.headers = self.config.headers
        self.timeout_s = self.config.timeout_s
        self.calendar_request_delay_s = self.config.calendar_request_delay_s
        self.calendar_cache_ttl_s = self.config.calendar_cache_ttl_s
        self._client: httpx.Client | None = None
        self._calendar_cache: dict[int, tuple[float, dict[str, Any]]] = {}

    def __enter__(self) -> "RaceScraper":
        self.startup()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.shutdown()

    def startup(self) -> None:
        """Initialize shared HTTP client and persist consent cookie for upstream pages."""
        self._get_client()
        consent_url = f"{self.base_url}/scrivi_cook.php?ritorno=calendario.php?ar=1"
        try:
            response = self._get_client().get(consent_url, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Cookie consent bootstrap failed: %s", exc)

    def shutdown(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(headers=self.headers, timeout=self.timeout_s)
        return self._client

    def _is_cache_fresh(self, fetched_at: float) -> bool:
        return (time.time() - fetched_at) < self.calendar_cache_ttl_s

    def _get_calendar_cache(self, stagione_key: int) -> dict[str, Any] | None:
        cached = self._calendar_cache.get(stagione_key)
        if cached:
            fetched_at, payload = cached
            if self._is_cache_fresh(fetched_at):
                return payload
            self._calendar_cache.pop(stagione_key, None)
        return None

    def _set_calendar_cache(self, stagione_key: int, payload: dict[str, Any]) -> None:
        self._calendar_cache[stagione_key] = (time.time(), payload)

    def fetch_html(self, url: str) -> BeautifulSoup:
        response = self._get_client().get(url)
        response.raise_for_status()
        response.encoding = "ISO-8859-1"
        return BeautifulSoup(response.text, "lxml")

    def fetch_text(self, url: str) -> str:
        response = self._get_client().get(url)
        response.raise_for_status()
        response.encoding = "ISO-8859-1"
        return response.text

    def parse_tables(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract all tables using first row as headers when available."""
        results: list[dict[str, Any]] = []
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            if not any(headers):
                continue
            data: list[Any] = []
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if any(cells):
                    if len(cells) == len(headers):
                        data.append(dict(zip(headers, cells)))
                    else:
                        data.append(cells)
            if data:
                results.append({"headers": headers, "rows": data})
        return results

    def parse_results_html(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        races: list[dict[str, Any]] = []

        for div in soup.find_all("div"):
            tables = div.find_all("table", recursive=False)
            if len(tables) < 2:
                continue

            header_table = next(
                (t for t in tables if t.find("td", class_="t3")), None
            )
            if not header_table:
                continue
            header_idx = tables.index(header_table)
            if header_idx + 1 >= len(tables):
                continue
            entries_table = tables[header_idx + 1]

            header_td = header_table.find("td", class_="t3")
            if not header_td:
                continue
            raw = header_td.get_text(" ", strip=True)
            m = re.search(r"GARA\s+(\d+)\s+del\s+(\d+)\s+Ore\s+([\d:]+)\s+(.+)", raw)
            if not m:
                continue

            race_num = int(m.group(1))
            date_day = m.group(2)
            time_str = m.group(3)
            rest = m.group(4).strip()

            phase_m = re.search(
                r"\s+((?:Time Trial|Qualificazione|Semifinale|Quarti di Finale|"
                r"Finale|Recupero|Knockout Round).*)$",
                rest, re.IGNORECASE,
            )
            phase = phase_m.group(1).strip() if phase_m else ""
            event_name = rest[:phase_m.start()].strip() if phase_m else rest

            all_tds = header_table.find_all("td")
            right_raw = all_tds[-1].get_text(" ", strip=True) if all_tds else ""

            def extract_int(pattern: str) -> int | None:
                mm = re.search(pattern, right_raw)
                return int(mm.group(1)) if mm else None

            qual_note_td = entries_table.find("td", class_="t0")
            qual_note = qual_note_td.get_text(strip=True) if qual_note_td else None

            finishers: list[dict[str, Any]] = []

            for td in entries_table.find_all("td", class_="t1"):
                for br in td.find_all("br"):
                    br.replace_with("\n")

                full_text = td.get_text("\n", strip=True)
                lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                if not lines:
                    continue

                pos_m = re.match(r"^(\d+)\s*([A-Z]{1,2})?$", lines[0])
                if not pos_m:
                    continue
                position = int(pos_m.group(1))
                master_class: str | None = pos_m.group(2) or None

                time_m = re.search(r"\((\d{2}:\d{2}:\d{2})\s*\)", lines[1]) if len(lines) > 1 else None
                finish_time: str | None = time_m.group(1) if time_m else None

                lane_bib_m = re.search(r"\((\d+)-(\d+)\)", lines[2]) if len(lines) > 2 else None
                lane: int | None = int(lane_bib_m.group(1)) if lane_bib_m else None
                bib: int | None = int(lane_bib_m.group(2)) if lane_bib_m else None

                club: str | None = None
                for b_tag in td.find_all("b"):
                    it_tag = b_tag.find("i")
                    if it_tag:
                        club = normalize_club_name(it_tag.get_text(strip=True))
                        break
                if club is None and len(lines) > 3:
                    club = normalize_club_name(lines[3])

                athletes: list[str] = []
                gap: str | None = None
                status: str | None = None
                guest_clubs: dict[str, str] = {}

                for line in lines[4:]:
                    fn_m = re.match(r"^\((\d+)\)\s+(.+)", line)
                    if re.match(r"^\+[\d:]+", line):
                        gap = line.split()[0]
                    elif re.match(r"^\*\*", line):
                        status = line.lstrip("*").strip()
                    elif fn_m:
                        guest_clubs[fn_m.group(1)] = fn_m.group(2)
                    elif re.match(r"^\.+$", line) or re.match(r"^\(?\d+\)?$", line):
                        pass
                    else:
                        clean = re.sub(r"\s*\d*\s*\([A-Z]{2}\)\s*$", "", line).strip()
                        clean = re.sub(r"\s*\(\d+\)\s*$", "", clean).strip()
                        if clean:
                            athletes.append(clean)

                finishers.append({
                    "position": position,
                    "master_class": master_class,
                    "time": finish_time,
                    "lane": lane,
                    "bib": bib,
                    "club": club,
                    "athletes": athletes,
                    "gap": gap,
                    "status": status,
                    "guest_clubs": guest_clubs,
                })

            races.append({
                "race_number": race_num,
                "date_day": date_day,
                "time": time_str,
                "event": event_name,
                "phase": phase,
                "distance_m": extract_int(r"(\d{3,4})\s+metri"),
                "codice": extract_int(r"Codice\s+(\d+)"),
                "n_equipaggi": extract_int(r"N\.Eq\.\s*(\d+)"),
                "n_iscritti": extract_int(r"N\.Isc\.\s*(\d+)"),
                "qual_note": qual_note,
                "finishers": finishers,
            })

        return races

    def parse_program_html(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        races: list[dict[str, Any]] = []

        for div in soup.find_all("div"):
            tables = div.find_all("table", recursive=False)
            if len(tables) < 2:
                continue

            header_table = next(
                (t for t in tables if t.find("td", class_="t3")), None
            )
            if not header_table:
                continue
            header_idx = tables.index(header_table)
            if header_idx + 1 >= len(tables):
                continue
            entries_table = tables[header_idx + 1]

            header_td = header_table.find("td", class_="t3")
            if not header_td:
                continue
            raw = header_td.get_text(" ", strip=True)
            m = re.search(r"GARA\s+(\d+)\s+del\s+(\d+)\s+Ore\s+([\d:]+)\s+(.+)", raw)
            if not m:
                continue

            race_num = int(m.group(1))
            date_day = m.group(2)
            time_str = m.group(3)
            rest = m.group(4).strip()

            phase_m = re.search(
                r"\s+((?:Time Trial|Qualificazione|Semifinale|Quarti di Finale|"
                r"Finale|Recupero|Knockout Round).*)$",
                rest, re.IGNORECASE,
            )
            phase = phase_m.group(1).strip() if phase_m else ""
            event_name = rest[:phase_m.start()].strip() if phase_m else rest

            all_tds = header_table.find_all("td")
            right_raw = all_tds[-1].get_text(" ", strip=True) if all_tds else ""

            def extract_int(pattern: str) -> int | None:
                mm = re.search(pattern, right_raw)
                return int(mm.group(1)) if mm else None

            qual_note_td = entries_table.find("td", class_="t0")
            qual_note = qual_note_td.get_text(strip=True) if qual_note_td else None

            entries: list[dict[str, Any]] = []
            for td in entries_table.find_all("td", class_="t1"):
                lines = [ln.strip() for ln in td.get_text("\n", strip=True).split("\n") if ln.strip()]
                if not lines:
                    continue

                lane_m = re.match(r"^(\d+)\s*(?:\((\d+)\))?$", lines[0])
                if not lane_m:
                    continue
                lane = int(lane_m.group(1))
                bib: int | None = int(lane_m.group(2)) if lane_m.group(2) else None

                club_tag = td.find("font", style=re.compile("font-weight:bolder"))
                club: str | None = normalize_club_name(club_tag.get_text(strip=True)) if club_tag else None

                athletes: list[str] = []
                guest_clubs: dict[str, str] = {}
                past_club = False

                for line in lines[1:]:
                    bib_m = re.match(r"^\((\d+)\)$", line)
                    guest_m = re.match(r"^\((\d+)\)\s+(.+)", line)
                    if bib_m and bib is None:
                        bib = int(bib_m.group(1))
                    elif guest_m:
                        guest_clubs[guest_m.group(1)] = guest_m.group(2)
                    elif re.match(r"^\.+$", line):
                        past_club = True
                    elif club and not past_club and normalize_club_name(line).casefold() == club.casefold():
                        past_club = True
                    elif club:
                        past_club = True
                        athlete = re.sub(r"\s*\d*\s*\([A-Z]{2}\)\s*$", "", line).strip()
                        athlete = re.sub(r"\s*\(\d+\)\s*$", "", athlete).strip()
                        if athlete:
                            athletes.append(athlete)

                entries.append({
                    "lane": lane,
                    "bib": bib,
                    "club": club,
                    "athletes": athletes,
                    "guest_clubs": guest_clubs,
                })

            races.append({
                "race_number": race_num,
                "date_day": date_day,
                "time": time_str,
                "event": event_name,
                "phase": phase,
                "distance_m": extract_int(r"(\d{3,4})\s+metri") or extract_int(r"mt/min\s+(\d+)"),
                "codice": extract_int(r"Codice\s+(\d+)"),
                "n_equipaggi": extract_int(r"N\.Eq\.\s*(\d+)"),
                "n_iscritti": extract_int(r"N\.Isc\.\s*(\d+)"),
                "qual_note": qual_note,
                "entries": entries,
            })

        return races

    def program_races_to_tables(self, races: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Project program races into the existing dashboard table shape."""
        headers = ["Ora", "Gara", "Evento", "Fase", "Corsia", "Pettorale", "Club", "Atleti", "Nota"]
        rows: list[dict[str, str]] = []

        for race in races:
            qual_note = race.get("qual_note") or ""
            entries = race.get("entries", [])
            has_data = any(entry.get("club") for entry in entries)

            if not has_data:
                rows.append(
                    {
                        "Ora": str(race.get("time") or ""),
                        "Gara": str(race.get("race_number") or ""),
                        "Evento": str(race.get("event") or ""),
                        "Fase": str(race.get("phase") or ""),
                        "Corsia": "-",
                        "Pettorale": "-",
                        "Club": "Da assegnare",
                        "Atleti": "",
                        "Nota": str(qual_note),
                    }
                )
                continue

            for entry in entries:
                if not entry.get("club"):
                    continue
                rows.append(
                    {
                        "Ora": str(race.get("time") or ""),
                        "Gara": str(race.get("race_number") or ""),
                        "Evento": str(race.get("event") or ""),
                        "Fase": str(race.get("phase") or ""),
                        "Corsia": str(entry.get("lane") or ""),
                        "Pettorale": str(entry.get("bib") or ""),
                        "Club": str(entry.get("club") or ""),
                        "Atleti": ", ".join(entry.get("athletes") or []),
                        "Nota": str(qual_note),
                    }
                )

        return [{"headers": headers, "rows": rows}] if rows else []

    def get_overview_soup(self, reg_id: str) -> BeautifulSoup:
        return self.fetch_html(f"{self.base_url}/menu_reg.php?reg={reg_id}&k1=R")

    def extract_results_urls(self, overview: BeautifulSoup) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        for anchor in overview.find_all("a", href=True):
            href = str(anchor["href"])
            if "dati/" not in href:
                continue
            row = anchor.find_parent("tr")
            row_text = row.get_text(strip=True).upper() if row else ""
            if "RISULTATI" not in row_text:
                continue
            label = ""
            if row:
                for td in row.find_all("td"):
                    td_text = td.get_text(strip=True)
                    if "RISULTATI" in td_text.upper():
                        label = td_text
                        break
            full_url = f"{self.base_url}/{href.lstrip('/')}"
            links.append({"label": label or href, "url": full_url})
        return links

    def get_results_payload(self, reg_id: str) -> dict[str, Any]:
        overview = self.get_overview_soup(reg_id)
        result_links = self.extract_results_urls(overview)
        if not result_links:
            raise DataNotAvailableError(f"No results published yet for regatta {reg_id}")

        all_races: list[dict[str, Any]] = []
        for link in result_links:
            races = self.parse_results_html(self.fetch_text(link["url"]))
            for race in races:
                race["source"] = link["label"]
            all_races.extend(races)

        return {
            "reg_id": reg_id,
            "source_urls": result_links,
            "race_count": len(all_races),
            "races": all_races,
        }

    def get_overview_payload(self, reg_id: str) -> dict[str, Any]:
        soup = self.get_overview_soup(reg_id)
        headings = [heading.get_text(strip=True) for heading in soup.find_all("h2")]

        data_links: dict[str, str] = {}
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if "dati/" in href:
                label = anchor.find_next("td")
                label_text = label.get_text(strip=True) if label else href
                data_links[label_text] = f"{self.base_url}/{href}"

        return {"reg_id": reg_id, "metadata": headings, "data_links": data_links}

    def get_program_payload(self, reg_id: str) -> dict[str, Any]:
        overview = self.get_overview_soup(reg_id)

        program_links: list[dict[str, str]] = []
        for anchor in overview.find_all("a", href=True):
            label = anchor.get_text(strip=True).upper()
            if "PROGRAMMA" not in label:
                parent = anchor.find_parent("td")
                if parent:
                    sibling = parent.find_next_sibling("td")
                    label = sibling.get_text(strip=True).upper() if sibling else ""

            if "PROGRAMMA" in label:
                href = str(anchor["href"])
                if not href.startswith("http"):
                    href = f"{self.base_url}/{href.lstrip('/')}"
                program_links.append({"label": label, "url": href})

        if not program_links:
            raise DataNotAvailableError(f"No program found for regatta {reg_id}")

        def priority_key(link: dict[str, str]) -> int:
            label = link["label"]
            if "COMPLETO" in label:
                return 0
            if "FINALI" in label:
                return 1
            if "GARE" in label:
                return 2
            if "PROVVIS" in label:
                return 3
            return 4

        program_links.sort(key=priority_key)
        best = program_links[0]

        try:
            program_html = self.fetch_text(best["url"])
        except httpx.HTTPError as exc:
            raise DataNotAvailableError(f"Could not fetch program at {best['url']}") from exc

        races = self.parse_program_html(program_html)

        return {
            "reg_id": reg_id,
            "program_type": best["label"],
            "source_url": best["url"],
            "all_program_urls": program_links,
            "race_count": len(races),
            "races": races,
            "tables": self.program_races_to_tables(races),
        }

    def get_crews_payload(self, reg_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/dati/ste{reg_id}.html"
        soup = self.fetch_html(url)
        return {"reg_id": reg_id, "source_url": url, "tables": self.parse_tables(soup)}

    def get_calendar_payload(self, stagione: int | None = None) -> dict[str, Any]:
        stagione_key = stagione if stagione is not None else 0
        cached_payload = self._get_calendar_cache(stagione_key)
        if cached_payload is not None:
            return cached_payload

        calendar_url = f"{self.base_url}/calendario.php?ar=1"
        if stagione is not None:
            calendar_url = f"{calendar_url}&stagione={stagione}"

        soup = self.fetch_html(calendar_url)

        manifestation_urls: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if "menu_nazionali_cal.php" in href:
                manifestation_urls.append(urljoin(f"{self.base_url}/", href))

        races: list[dict[str, str | None]] = []
        seen_reg_ids: set[str] = set()

        for index, manifestation_url in enumerate(manifestation_urls):
            if index > 0 and self.calendar_request_delay_s > 0:
                time.sleep(self.calendar_request_delay_s)

            try:
                manifestation_soup = self.fetch_html(manifestation_url)
            except httpx.HTTPError:
                continue

            for anchor in manifestation_soup.find_all("a", href=True):
                href = str(anchor["href"])
                match = re.search(r"reg=([A-Za-z0-9]+)", href)
                if not match:
                    continue

                reg_id = match.group(1)
                if reg_id in seen_reg_ids:
                    continue
                seen_reg_ids.add(reg_id)

                row = anchor.find_parent("tr")
                cells = [td.get_text(strip=True) for td in row.find_all("td")] if row else []

                races.append(
                    {
                        "reg_id": reg_id,
                        "date": cells[1] if len(cells) > 1 else None,
                        "location": cells[2] if len(cells) > 2 else None,
                        "name": cells[3] if len(cells) > 3 else anchor.get_text(strip=True) or None,
                        "url": f"{self.base_url}/menu_reg.php?reg={reg_id}&k1=R",
                    }
                )

        result = {"count": len(races), "races": races}
        self._set_calendar_cache(stagione_key, result)
        return result

    def parse_live_races_html(self, html: str) -> list[dict[str, str]]:
        """Extract live races from menu_diretta HTML anchors."""
        soup = BeautifulSoup(html, "lxml")
        races: list[dict[str, str]] = []
        seen_reg_ids: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if "menu_reg.php" not in href or "reg=" not in href:
                continue

            full_url = urljoin(f"{self.base_url}/", href)
            parsed = urlparse(full_url)
            query = parse_qs(parsed.query)
            reg_id = (query.get("reg") or [""])[0].strip()
            if not reg_id or reg_id in seen_reg_ids:
                continue

            k1_value = (query.get("k1") or [""])[0].strip().upper()
            if k1_value != "D":
                continue

            row = anchor.find_parent("tr")
            cells = row.find_all("td") if row else []
            date = ""
            location = ""
            name = ""

            if len(cells) >= 4:
                date = cells[1].get_text(strip=True)
                location = cells[2].get_text(strip=True)
                name = cells[3].get_text(strip=True)
            elif len(cells) >= 2:
                name = cells[-1].get_text(strip=True)

            if not name:
                name = anchor.get_text(" ", strip=True) or reg_id

            races.append(
                {
                    "reg_id": reg_id,
                    "date": date,
                    "location": location,
                    "name": name,
                    "url": full_url,
                }
            )
            seen_reg_ids.add(reg_id)

        return races

    def get_live_races_payload(self) -> dict[str, Any]:
        """Fetch and parse currently live races from menu_diretta."""
        source_url = f"{self.base_url}/menu_diretta.php"
        html = self.fetch_text(source_url)
        races = self.parse_live_races_html(html)

        return {
            "source_url": source_url,
            "count": len(races),
            "races": races,
        }

    def filter_races_for_team(self, races: list[dict[str, Any]], team: str) -> list[dict[str, Any]]:
        return [
            race
            for race in races
            if any(finisher_matches_team(finisher, team) for finisher in race.get("finishers", []))
        ]

    def filter_program_tables_for_team(self, tables: list[dict[str, Any]], team: str) -> list[dict[str, Any]]:
        """Filter program rows to those containing the selected team in any cell."""
        team_key = normalize_club_name(team).casefold()
        if not team_key:
            return []

        filtered_tables: list[dict[str, Any]] = []
        for table in tables:
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            matched_rows: list[Any] = []

            for row in rows:
                if isinstance(row, dict):
                    values = [str(value) for value in row.values()]
                else:
                    values = [str(value) for value in row]

                normalized_cells = [normalize_club_name(value).casefold() for value in values]
                if any(team_key in cell for cell in normalized_cells):
                    matched_rows.append(row)

            if matched_rows:
                filtered_tables.append({"headers": headers, "rows": matched_rows})

        return filtered_tables


def fetch_calendar(stagione: int | None = None) -> dict[str, Any]:
    with RaceScraper() as scraper:
        return scraper.get_calendar_payload(stagione=stagione)


def fetch_race_results(reg_id: str) -> dict[str, Any]:
    with RaceScraper() as scraper:
        return scraper.get_results_payload(reg_id)


def fetch_race_program(reg_id: str) -> dict[str, Any]:
    with RaceScraper() as scraper:
        return scraper.get_program_payload(reg_id)


def fetch_race_overview(reg_id: str) -> dict[str, Any]:
    with RaceScraper() as scraper:
        return scraper.get_overview_payload(reg_id)


def fetch_live_races() -> dict[str, Any]:
    with RaceScraper() as scraper:
        return scraper.get_live_races_payload()

