"""
client.py — NSW Online Registry court lists API client

The public site is at onlineregistry.lawlink.nsw.gov.au (Drupal + Angular cls-web).
Court list data is loaded from a separate JSON API (same behaviour as the SPA’s
$http.jsonp calls; plain GET with Accept: application/json also works).

  GET https://api.onlineregistry.justice.nsw.gov.au/courtlistsearch/listings
      ?offset=0
      &count=30
      &nameOfParty=Capitol+Constructions   (or &caseNumber=… for file numbers)
      &startDate=YYYY-MM-DD
      &endDate=YYYY-MM-DD
      &sortField=date,time,location
      &sortOrder=ASC

The SPA builds start/end from filters like “Next 3 weeks”; see _date_range().
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Generator

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_API_URL = (
    "https://api.onlineregistry.justice.nsw.gov.au/courtlistsearch/listings"
)
PAGE_SIZE = 30
REQUEST_DELAY = 2.0    # seconds between pages — be polite to the server

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": "https://onlineregistry.lawlink.nsw.gov.au/content/court-lists",
    "User-Agent": (
        "Mozilla/5.0 (compatible; CourtScraper/1.0; "
        "+https://yoursite.com.au/about)"   # <-- update with your site
    ),
}


class RegistryAPIError(Exception):
    pass


def _looks_like_case_number(term: str) -> bool:
    """Match cls-web SearchController S(e): NNNN/NNNNNNNN or 12 digits."""
    t = term.strip()
    return bool(re.fullmatch(r"\d{4}/\d{8}", t)) or bool(re.fullmatch(r"\d{12}", t))


def _date_range(date_filter: str, today: date | None = None) -> tuple[str, str]:
    """
    Return (startDate, endDate) as YYYY-MM-DD, aligned with cls-web
    SearchController date filter switch (moment.js semantics).
    """
    today = today or date.today()
    key = date_filter.strip()

    if key == "Today":
        d = today.isoformat()
        return d, d

    if key == "This week":
        # Monday–Friday of the calendar week containing today (ISO weekday).
        monday = today - timedelta(days=today.weekday())
        friday = monday + timedelta(days=4)
        return monday.isoformat(), friday.isoformat()

    if key == "Next 3 weeks":
        return today.isoformat(), (today + timedelta(weeks=3)).isoformat()

    if key == "Last 7 days":
        return (today - timedelta(days=7)).isoformat(), today.isoformat()

    if key == "All available dates":
        return (
            (today - timedelta(days=7)).isoformat(),
            (today + timedelta(weeks=3)).isoformat(),
        )

    # Specific calendar day from date picker: "D MMM YYYY" (e.g. 7 Apr 2026)
    try:
        parsed = datetime.strptime(key, "%d %b %Y").date()
        d = parsed.isoformat()
        return d, d
    except ValueError:
        pass

    logger.warning("Unknown date_filter %r; using Next 3 weeks", date_filter)
    return today.isoformat(), (today + timedelta(weeks=3)).isoformat()


class RegistryClient:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)

    @retry(
        retry=retry_if_exception_type((requests.RequestException, RegistryAPIError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _get_page(self, search_term: str, offset: int, date_filter: str) -> dict:
        start_d, end_d = _date_range(date_filter)
        params: dict[str, str | int] = {
            "offset": offset,
            "count": PAGE_SIZE,
            "startDate": start_d,
            "endDate": end_d,
            "sortField": "date,time,location",
            "sortOrder": "ASC",
        }
        term = search_term.strip()
        if _looks_like_case_number(term):
            params["caseNumber"] = term.replace("/", "")
        else:
            params["nameOfParty"] = term

        resp = self.session.get(BASE_API_URL, params=params, timeout=20)

        if resp.status_code == 429:
            raise RegistryAPIError(f"Rate limited (429) fetching {search_term!r}")
        if resp.status_code >= 400:
            raise RegistryAPIError(
                f"HTTP {resp.status_code} for {search_term!r} offset={offset}"
            )

        try:
            data = resp.json()
        except ValueError as e:
            raise RegistryAPIError(f"Non-JSON response: {resp.text[:200]}") from e

        return data

    def search(
        self,
        search_term: str,
        date_filter: str = "All available dates",
    ) -> Generator[dict, None, None]:
        """
        Paginate through all results for search_term.
        Yields one raw listing dict per court matter.
        """
        offset = 0
        total = None

        while True:
            logger.debug(f"Fetching {search_term!r} offset={offset}")
            data = self._get_page(search_term, offset, date_filter)

            results = (
                data.get("hits")
                or data.get("results")
                or data.get("items")
                or data.get("data")
                or []
            )

            if total is None:
                total = int(data.get("total") or data.get("count") or len(results))
                logger.info(
                    f"Search {search_term!r}: {total} total results"
                )

            for item in results:
                yield item

            offset += PAGE_SIZE
            if offset >= total or not results:
                break

            time.sleep(REQUEST_DELAY)


def _parties_display(raw: dict) -> str | None:
    if raw.get("case_title"):
        return str(raw["case_title"])
    parties = raw.get("parties")
    if isinstance(parties, list) and parties:
        names = []
        for p in parties:
            if isinstance(p, dict) and p.get("party_name"):
                names.append(str(p["party_name"]))
        return ", ".join(names) if names else None
    return None


def parse_listing(raw: dict) -> dict:
    """
    Map a raw API result dict to our DB schema columns.

    Field names match api.onlineregistry.justice.nsw.gov.au courtlistsearch
    listings JSON (scm_* / jl_* keys).
    """
    return {
        "external_id": str(raw.get("id") or ""),
        "case_number": raw.get("scm_case_number"),
        "parties": _parties_display(raw),
        "listing_date": _parse_date(
            raw.get("scm_dateyear") or raw.get("scm_date") or raw.get("listingDate")
        ),
        "listing_time": raw.get("time_listed") or raw.get("time") or raw.get("listingTime"),
        "court": raw.get("scm_jurisdiction_court_short") or raw.get("court"),
        "location": raw.get("location") or raw.get("address") or raw.get("courthouse"),
        "courtroom": raw.get("court_room_name") or raw.get("courtroom") or raw.get("room"),
        "jurisdiction": raw.get("scm_jurisdiction_type") or raw.get("jurisdiction"),
        "listing_type": raw.get("jl_listing_type_ds") or raw.get("listingType") or raw.get("type"),
        "presiding_officer": raw.get("officers.display_name")
            or raw.get("officers.scm_presiding_officer")
            or raw.get("presidingOfficer")
            or raw.get("judge"),
        "raw_json": raw,
    }


def _parse_date(value):
    """Normalise date strings to YYYY-MM-DD for DATE columns."""
    if not value:
        return None
    s = str(value).strip()
    if len(s) == 10 and s[4] == "-":
        return s
    try:
        return datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        return datetime.strptime(s, "%d %b %Y").strftime("%Y-%m-%d")
    except ValueError:
        pass
    return s
