"""
test_client.py — unit tests for scraper/client.py.

No database or network required. The NSW API is not called.
"""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from scraper.client import _date_range, _looks_like_case_number, parse_listing


# ---------------------------------------------------------------------------
# _date_range
# ---------------------------------------------------------------------------

class TestDateRange:
    TODAY = date(2026, 4, 10)

    def test_all_available_dates(self):
        start, end = _date_range("All available dates", today=self.TODAY)
        assert start == "2026-04-03"   # today - 7 days
        assert end   == "2026-05-01"   # today + 3 weeks

    def test_next_3_weeks(self):
        start, end = _date_range("Next 3 weeks", today=self.TODAY)
        assert start == "2026-04-10"
        assert end   == "2026-05-01"

    def test_today(self):
        start, end = _date_range("Today", today=self.TODAY)
        assert start == end == "2026-04-10"

    def test_this_week_returns_monday_to_friday(self):
        # 2026-04-10 is a Friday
        start, end = _date_range("This week", today=self.TODAY)
        assert start == "2026-04-06"   # Monday
        assert end   == "2026-04-10"   # Friday

    def test_last_7_days(self):
        start, end = _date_range("Last 7 days", today=self.TODAY)
        assert start == "2026-04-03"
        assert end   == "2026-04-10"

    def test_specific_date_string(self):
        start, end = _date_range("22 Apr 2026", today=self.TODAY)
        assert start == end == "2026-04-22"

    def test_unknown_filter_falls_back_to_next_3_weeks(self):
        start, end = _date_range("garbage value", today=self.TODAY)
        assert start == "2026-04-10"
        assert end   == "2026-05-01"


# ---------------------------------------------------------------------------
# _looks_like_case_number
# ---------------------------------------------------------------------------

class TestLooksLikeCaseNumber:
    def test_slash_format(self):
        assert _looks_like_case_number("2025/00231569") is True

    def test_12_digit_format(self):
        assert _looks_like_case_number("202500231569") is True

    def test_plain_name_is_false(self):
        assert _looks_like_case_number("Vogue Homes") is False

    def test_partial_number_is_false(self):
        assert _looks_like_case_number("2025/123") is False

    def test_empty_string_is_false(self):
        assert _looks_like_case_number("") is False


# ---------------------------------------------------------------------------
# parse_listing
# ---------------------------------------------------------------------------

class TestParseListing:
    LIVE_HIT = {
        "id": "20250023156931041486ContestedHearing",
        "scm_case_number": "2025/00231569",
        "case_title": "Oscar Downing v CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW",
        "scm_dateyear": "22 Apr 2026",
        "time_listed": "9:15 am",
        "scm_jurisdiction_court_short": "NCAT CCD",
        "location": "NCAT Liverpool (CCD)",
        "court_room_name": "Unassigned",
        "scm_jurisdiction_type": "NCAT",
        "jl_listing_type_ds": "Contested Hearing",
        "scm_phone": "1300 679 272",
    }

    def test_external_id(self):
        result = parse_listing(self.LIVE_HIT)
        assert result["external_id"] == "20250023156931041486ContestedHearing"

    def test_external_id_nonempty(self):
        result = parse_listing(self.LIVE_HIT)
        assert bool(result["external_id"]) is True

    def test_case_number(self):
        assert parse_listing(self.LIVE_HIT)["case_number"] == "2025/00231569"

    def test_parties_from_case_title(self):
        result = parse_listing(self.LIVE_HIT)
        assert "CAPITOL CONSTRUCTIONS" in result["parties"]
        assert "VOGUE HOMES" in result["parties"]

    def test_listing_date_parsed_to_iso(self):
        assert parse_listing(self.LIVE_HIT)["listing_date"] == "2026-04-22"

    def test_listing_time(self):
        assert parse_listing(self.LIVE_HIT)["listing_time"] == "9:15 am"

    def test_court(self):
        assert parse_listing(self.LIVE_HIT)["court"] == "NCAT CCD"

    def test_location(self):
        assert parse_listing(self.LIVE_HIT)["location"] == "NCAT Liverpool (CCD)"

    def test_courtroom(self):
        assert parse_listing(self.LIVE_HIT)["courtroom"] == "Unassigned"

    def test_jurisdiction(self):
        assert parse_listing(self.LIVE_HIT)["jurisdiction"] == "NCAT"

    def test_listing_type(self):
        assert parse_listing(self.LIVE_HIT)["listing_type"] == "Contested Hearing"

    def test_presiding_officer_absent_is_none(self):
        assert parse_listing(self.LIVE_HIT)["presiding_officer"] is None

    def test_raw_json_is_original_dict(self):
        result = parse_listing(self.LIVE_HIT)
        assert result["raw_json"] is self.LIVE_HIT

    def test_empty_id_produces_empty_external_id(self):
        result = parse_listing({})
        assert result["external_id"] == ""

    def test_unmapped_fields_not_in_result(self):
        result = parse_listing(self.LIVE_HIT)
        assert "scm_phone" not in result
        assert "scm_jurisdiction_court_group" not in result
