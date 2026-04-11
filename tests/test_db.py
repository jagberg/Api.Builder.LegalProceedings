"""
test_db.py — integration tests for scraper/db.py helpers.

Tests exercise the real database directly (no Flask layer).
Requires: docker compose up -d db
"""

import json
import pytest
from scraper.db import (
    create_builder,
    fetch_active_aliases,
    finish_run,
    start_run,
    update_builders_last_scraped,
    upsert_listing,
)


# ---------------------------------------------------------------------------
# fetch_active_aliases
# ---------------------------------------------------------------------------

class TestFetchActiveAliases:
    def test_returns_empty_when_no_builders(self, db_conn, clean_db):
        assert fetch_active_aliases(db_conn) == []

    def test_returns_all_aliases(self, db_conn, seed_vogue):
        aliases = fetch_active_aliases(db_conn)
        assert len(aliases) == 2
        names = {a["alias_name"] for a in aliases}
        assert names == {"Vogue Homes", "Capitol Constructions"}

    def test_all_aliases_share_builder_id(self, db_conn, seed_vogue):
        aliases = fetch_active_aliases(db_conn)
        builder_ids = {a["builder_id"] for a in aliases}
        assert len(builder_ids) == 1
        assert builder_ids.pop() == seed_vogue

    def test_builder_name_included(self, db_conn, seed_vogue):
        aliases = fetch_active_aliases(db_conn)
        for a in aliases:
            assert a["builder_name"] == "Vogue Homes"

    def test_inactive_builder_excluded(self, db_conn, clean_db):
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name, is_active) VALUES ('Inactive Co', 0) RETURNING id"
            )
            bid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO builder_aliases (builder_id, alias_name) VALUES (%s, 'Inactive Co')",
                (bid,),
            )
        db_conn.commit()
        assert fetch_active_aliases(db_conn) == []

    def test_due_only_includes_never_scraped(self, db_conn, seed_vogue):
        aliases = fetch_active_aliases(db_conn, due_only=True)
        assert len(aliases) == 2

    def test_due_only_skips_recently_scraped(self, db_conn, clean_db):
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name, scrape_interval_days, last_scraped_at) "
                "VALUES ('Fresh Builder', 1, NOW()) RETURNING id"
            )
            bid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO builder_aliases (builder_id, alias_name) VALUES (%s, 'Fresh Builder')",
                (bid,),
            )
        db_conn.commit()
        aliases = fetch_active_aliases(db_conn, due_only=True)
        assert aliases == []

    def test_due_only_includes_overdue(self, db_conn, clean_db):
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name, scrape_interval_days, last_scraped_at) "
                "VALUES ('Overdue Builder', 1, NOW() - INTERVAL '2 days') RETURNING id"
            )
            bid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO builder_aliases (builder_id, alias_name) VALUES (%s, 'Overdue Builder')",
                (bid,),
            )
        db_conn.commit()
        aliases = fetch_active_aliases(db_conn, due_only=True)
        assert len(aliases) == 1
        assert aliases[0]["alias_name"] == "Overdue Builder"


# ---------------------------------------------------------------------------
# create_builder
# ---------------------------------------------------------------------------

class TestCreateBuilder:
    def test_creates_builder_row(self, db_conn, clean_db):
        result = create_builder(db_conn, "New Builder")
        assert result["builder_name"] == "New Builder"
        assert result["scrape_interval_days"] == 20

    def test_creates_first_alias_automatically(self, db_conn, clean_db):
        create_builder(db_conn, "New Builder")
        aliases = fetch_active_aliases(db_conn)
        assert len(aliases) == 1
        assert aliases[0]["alias_name"] == "New Builder"

    def test_custom_interval(self, db_conn, clean_db):
        result = create_builder(db_conn, "Daily Builder", scrape_interval_days=1)
        assert result["scrape_interval_days"] == 1

    def test_idempotent_on_duplicate_name(self, db_conn, clean_db):
        create_builder(db_conn, "Same Name")
        create_builder(db_conn, "Same Name")   # must not raise
        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM builders WHERE builder_name = 'Same Name'")
            assert cur.fetchone()[0] == 1


# ---------------------------------------------------------------------------
# upsert_listing
# ---------------------------------------------------------------------------

class TestUpsertListing:
    @pytest.fixture()
    def run_id(self, db_conn, seed_vogue):
        return start_run(db_conn)

    @pytest.fixture()
    def sample_listing(self):
        return {
            "external_id":       "test001ContestedHearing",
            "case_number":       "2025/00100001",
            "parties":           "John Smith v VOGUE HOMES NSW PTY LTD",
            "listing_date":      "2026-04-22",
            "listing_time":      "09:15:00",
            "court":             "NCAT CCD",
            "location":          "NCAT Liverpool (CCD)",
            "courtroom":         "Courtroom 3",
            "jurisdiction":      "NCAT",
            "listing_type":      "Contested Hearing",
            "presiding_officer": None,
            "raw_json":          {"id": "test001ContestedHearing"},
        }

    def test_insert_returns_true(self, db_conn, seed_vogue, run_id, sample_listing):
        is_new = upsert_listing(db_conn, seed_vogue, "Vogue Homes", run_id, sample_listing)
        assert is_new is True

    def test_update_returns_false(self, db_conn, seed_vogue, run_id, sample_listing):
        upsert_listing(db_conn, seed_vogue, "Vogue Homes", run_id, sample_listing)
        is_new = upsert_listing(db_conn, seed_vogue, "Vogue Homes", run_id, sample_listing)
        assert is_new is False

    def test_listing_stored_in_db(self, db_conn, seed_vogue, run_id, sample_listing):
        upsert_listing(db_conn, seed_vogue, "Vogue Homes", run_id, sample_listing)
        with db_conn.cursor() as cur:
            cur.execute("SELECT case_number, court FROM court_listings WHERE external_id = %s",
                        ("test001ContestedHearing",))
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "2025/00100001"
        assert row[1] == "NCAT CCD"

    def test_matched_alias_stored(self, db_conn, seed_vogue, run_id, sample_listing):
        upsert_listing(db_conn, seed_vogue, "Capitol Constructions", run_id, sample_listing)
        with db_conn.cursor() as cur:
            cur.execute("SELECT matched_alias FROM court_listings WHERE external_id = %s",
                        ("test001ContestedHearing",))
            assert cur.fetchone()[0] == "Capitol Constructions"

    def test_first_seen_run_not_overwritten_on_update(self, db_conn, seed_vogue,
                                                       run_id, sample_listing):
        upsert_listing(db_conn, seed_vogue, "Vogue Homes", run_id, sample_listing)
        run_id_2 = start_run(db_conn)
        upsert_listing(db_conn, seed_vogue, "Vogue Homes", run_id_2, sample_listing)
        with db_conn.cursor() as cur:
            cur.execute("SELECT first_seen_run, last_seen_run FROM court_listings "
                        "WHERE external_id = %s", ("test001ContestedHearing",))
            first, last = cur.fetchone()
        assert first == run_id
        assert last == run_id_2


# ---------------------------------------------------------------------------
# update_builders_last_scraped
# ---------------------------------------------------------------------------

class TestUpdateBuildersLastScraped:
    def test_updates_timestamp(self, db_conn, seed_vogue):
        update_builders_last_scraped(db_conn, {seed_vogue})
        with db_conn.cursor() as cur:
            cur.execute("SELECT last_scraped_at FROM builders WHERE id = %s", (seed_vogue,))
            assert cur.fetchone()[0] is not None

    def test_empty_set_is_safe(self, db_conn, seed_vogue):
        update_builders_last_scraped(db_conn, set())   # must not raise


# ---------------------------------------------------------------------------
# start_run / finish_run
# ---------------------------------------------------------------------------

class TestScrapeRuns:
    def test_start_run_returns_id(self, db_conn, clean_db):
        run_id = start_run(db_conn)
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_finish_run_updates_status(self, db_conn, clean_db):
        run_id = start_run(db_conn)
        finish_run(db_conn, run_id, "success", 2, 10, 3)
        with db_conn.cursor() as cur:
            cur.execute("SELECT status, aliases_processed, listings_found, listings_new "
                        "FROM scrape_runs WHERE id = %s", (run_id,))
            row = cur.fetchone()
        assert row[0] == "success"
        assert row[1] == 2
        assert row[2] == 10
        assert row[3] == 3
