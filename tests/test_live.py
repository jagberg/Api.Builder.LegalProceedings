"""
test_live.py — smoke tests against the real NSW Registry API.

Run manually:  pytest tests/test_live.py -v
Run via CI:    .github/workflows/live-tests.yml (weekly schedule)

No database or Flask app required. All five tests share a single API call
so we hit the registry server exactly once per run.
"""

import pytest
from scraper.client import RegistryClient, _date_range, parse_listing

# A search term with a known history of NCAT hearings.
# Using the alias form to also exercise that path.
_SEARCH_TERM = "Vogue Homes"

# Fields that every hit from the NSW Registry must contain.
_REQUIRED_FIELDS = {
    "id",
    "scm_case_number",
    "case_title",
    "scm_dateyear",
    "scm_jurisdiction_court_short",
    "scm_jurisdiction_type",
}


@pytest.fixture(scope="module")
def live_hits():
    """
    Single live API call shared across all tests in this module.
    Returns a list (may be empty — no active hearings is still a valid state).
    Raises on network error, HTTP 4xx/5xx, or non-JSON response.
    """
    client = RegistryClient()
    return list(client.search(_SEARCH_TERM, date_filter="All available dates"))


# ---------------------------------------------------------------------------
# Test 1 — API is reachable and returns a list
# ---------------------------------------------------------------------------

def test_api_reachable_returns_list(live_hits):
    """Registry API responds without error and yields a Python list."""
    assert isinstance(live_hits, list)


# ---------------------------------------------------------------------------
# Test 2 — Response structure is valid
# ---------------------------------------------------------------------------

def test_hits_have_required_fields(live_hits):
    """Every hit includes the fields that parse_listing() depends on."""
    if not live_hits:
        pytest.skip("No active listings for search term — field check skipped")
    for hit in live_hits:
        missing = _REQUIRED_FIELDS - hit.keys()
        assert not missing, f"Hit is missing required fields: {missing}\nHit: {hit}"


# ---------------------------------------------------------------------------
# Test 3 — parse_listing maps a real hit without error
# ---------------------------------------------------------------------------

def test_parse_listing_on_live_hit(live_hits):
    """parse_listing() can process the first real hit and produce required keys."""
    if not live_hits:
        pytest.skip("No active listings returned — parse test skipped")
    parsed = parse_listing(live_hits[0])
    assert parsed["external_id"], "external_id must be non-empty"
    assert parsed["listing_date"],  "listing_date must be non-empty"
    # Date should be in YYYY-MM-DD format
    assert len(parsed["listing_date"]) == 10 and parsed["listing_date"][4] == "-", (
        f"listing_date not in YYYY-MM-DD format: {parsed['listing_date']!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Date range helper returns a sensible window
# ---------------------------------------------------------------------------

def test_date_range_all_available_is_valid():
    """_date_range('All available dates') returns start < end in YYYY-MM-DD."""
    start, end = _date_range("All available dates")
    assert len(start) == 10 and start[4] == "-", f"Bad start format: {start!r}"
    assert len(end) == 10 and end[4] == "-",   f"Bad end format: {end!r}"
    assert start < end, f"Expected start < end, got {start!r} >= {end!r}"


# ---------------------------------------------------------------------------
# Test 5 — Alias search also hits the API without error
# ---------------------------------------------------------------------------

def test_alias_search_returns_list():
    """Searching by alias 'Capitol Constructions' reaches the API without error."""
    client = RegistryClient()
    results = list(client.search("Capitol Constructions", date_filter="All available dates"))
    assert isinstance(results, list)
