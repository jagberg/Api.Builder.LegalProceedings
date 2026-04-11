"""
test_api.py — integration tests for Flask API endpoints.

All tests hit the real database and use a mocked NSW registry API.
Requires: docker compose up -d db
"""

import pytest


# ---------------------------------------------------------------------------
# GET /builders
# ---------------------------------------------------------------------------

class TestListBuilders:
    def test_empty(self, client, clean_db):
        r = client.get("/builders")
        assert r.status_code == 200
        assert r.json["builders"] == []

    def test_returns_builder_with_aliases(self, client, seed_vogue):
        r = client.get("/builders")
        assert r.status_code == 200
        builders = r.json["builders"]
        assert len(builders) == 1
        b = builders[0]
        assert b["builder_name"] == "Vogue Homes"
        assert b["is_active"] is True
        assert b["scrape_interval_days"] == 1
        assert set(b["aliases"]) == {"Vogue Homes", "Capitol Constructions"}
        assert b["last_scraped_at"] is None

    def test_multiple_builders(self, client, db_conn, clean_db):
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name, scrape_interval_days) VALUES "
                "('Builder A', 1), ('Builder B', 20)"
            )
        db_conn.commit()

        r = client.get("/builders")
        assert r.status_code == 200
        names = [b["builder_name"] for b in r.json["builders"]]
        assert "Builder A" in names
        assert "Builder B" in names


# ---------------------------------------------------------------------------
# GET /builders/<name>/hearings
# ---------------------------------------------------------------------------

class TestGetHearings:
    def test_unknown_builder_returns_404(self, client, clean_db):
        r = client.get("/builders/Nobody/hearings")
        assert r.status_code == 404
        assert "not found" in r.json["error"].lower()

    def test_returns_empty_when_no_listings(self, client, seed_vogue):
        r = client.get("/builders/Vogue Homes/hearings")
        assert r.status_code == 200
        assert r.json["total"] == 0
        assert r.json["hearings"] == []

    def test_returns_hearings_by_primary_name(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings")
        assert r.status_code == 200
        data = r.json
        assert data["total"] == 1
        assert data["builder_name"] == "Vogue Homes"
        assert data["resolved_alias"] is False
        h = data["hearings"][0]
        assert h["external_id"] == "test001ContestedHearing"
        assert h["case_number"] == "2025/00100001"
        assert h["listing_date"] == "2026-04-22"
        assert h["court"] == "NCAT CCD"

    def test_alias_resolves_to_same_results(self, client, seed_listing):
        """Capitol Constructions must return identical hearings to Vogue Homes."""
        by_primary = client.get("/builders/Vogue Homes/hearings").json
        by_alias   = client.get("/builders/Capitol Constructions/hearings").json

        assert by_alias["builder_name"]   == "Vogue Homes"
        assert by_alias["searched_for"]   == "Capitol Constructions"
        assert by_alias["resolved_alias"] is True
        assert by_alias["aliases"]        == by_primary["aliases"]
        assert by_alias["total"]          == by_primary["total"]
        assert by_alias["hearings"][0]["external_id"] == by_primary["hearings"][0]["external_id"]

    def test_response_includes_aliases_list(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings")
        assert set(r.json["aliases"]) == {"Vogue Homes", "Capitol Constructions"}

    def test_date_filter_from_date_excludes_old(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings?from_date=2027-01-01")
        assert r.status_code == 200
        assert r.json["total"] == 0

    def test_date_filter_from_date_includes_match(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings?from_date=2026-04-01")
        assert r.status_code == 200
        assert r.json["total"] == 1

    def test_date_filter_to_date(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings?to_date=2026-04-01")
        assert r.status_code == 200
        assert r.json["total"] == 0

    def test_pagination_limit(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings?limit=0&offset=0")
        # limit=0 → still valid, just returns no rows
        assert r.status_code == 200

    def test_pagination_offset_beyond_total(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings?offset=999")
        assert r.status_code == 200
        assert r.json["hearings"] == []

    def test_invalid_limit_returns_400(self, client, seed_vogue):
        r = client.get("/builders/Vogue Homes/hearings?limit=abc")
        assert r.status_code == 400

    def test_limit_capped_at_200(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings?limit=9999")
        assert r.status_code == 200
        assert r.json["limit"] == 200


# ---------------------------------------------------------------------------
# POST /builders/<name>/scrape
# ---------------------------------------------------------------------------

class TestScrapeBuilder:
    def test_scrapes_existing_builder(self, client, seed_vogue, mock_nsw_api):
        r = client.post("/builders/Vogue Homes/scrape")
        assert r.status_code == 200
        data = r.json
        assert data["builder_created"] is False
        assert data["aliases_processed"] == 2   # Vogue Homes + Capitol Constructions
        assert data["listings_found"] == 2       # one hit per alias
        assert data["listings_new"] == 1         # same external_id → deduped on second alias

    def test_auto_creates_unknown_builder(self, client, clean_db, mock_nsw_empty):
        r = client.post("/builders/Brand New Builder/scrape")
        assert r.status_code == 201
        data = r.json
        assert data["builder_created"] is True
        assert data["scrape_interval_days"] == 20
        assert data["aliases_processed"] == 1

    def test_auto_created_builder_appears_in_list(self, client, clean_db, mock_nsw_empty):
        client.post("/builders/Brand New Builder/scrape")
        r = client.get("/builders")
        names = [b["builder_name"] for b in r.json["builders"]]
        assert "Brand New Builder" in names

    def test_auto_created_builder_has_20_day_interval(self, client, clean_db, mock_nsw_empty):
        client.post("/builders/Brand New Builder/scrape")
        r = client.get("/builders")
        b = next(b for b in r.json["builders"] if b["builder_name"] == "Brand New Builder")
        assert b["scrape_interval_days"] == 20

    def test_scrape_writes_listings_to_db(self, client, seed_vogue, mock_nsw_api):
        client.post("/builders/Vogue Homes/scrape")
        r = client.get("/builders/Vogue Homes/hearings")
        assert r.json["total"] == 1
        assert r.json["hearings"][0]["external_id"] == "test001ContestedHearing"

    def test_scrape_idempotent(self, client, seed_vogue, mock_nsw_api):
        """Running the same scrape twice must not create duplicate listings."""
        client.post("/builders/Vogue Homes/scrape")
        r2 = client.post("/builders/Vogue Homes/scrape")
        assert r2.json["listings_new"] == 0
        r = client.get("/builders/Vogue Homes/hearings")
        assert r.json["total"] == 1

    def test_updates_last_scraped_at(self, client, seed_vogue, mock_nsw_empty):
        client.post("/builders/Vogue Homes/scrape")
        r = client.get("/builders")
        b = next(b for b in r.json["builders"] if b["builder_name"] == "Vogue Homes")
        assert b["last_scraped_at"] is not None


# ---------------------------------------------------------------------------
# POST /builders/scrape  (all builders, due_only)
# ---------------------------------------------------------------------------

class TestScrapeAll:
    def test_scrapes_due_builders(self, client, seed_vogue, mock_nsw_api):
        r = client.post("/builders/scrape")
        assert r.status_code == 200
        assert r.json["aliases_processed"] == 2

    def test_skips_recently_scraped_builder(self, client, db_conn, clean_db, mock_nsw_api):
        """A builder scraped moments ago must be skipped on the next cron call."""
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name, scrape_interval_days, last_scraped_at) "
                "VALUES ('Recent Builder', 1, NOW()) RETURNING id"
            )
            bid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO builder_aliases (builder_id, alias_name) VALUES (%s, 'Recent Builder')",
                (bid,),
            )
        db_conn.commit()

        r = client.post("/builders/scrape")
        assert r.json["aliases_processed"] == 0

    def test_includes_never_scraped_builder(self, client, db_conn, clean_db, mock_nsw_empty):
        """last_scraped_at IS NULL means the builder is always due."""
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name, scrape_interval_days) "
                "VALUES ('Never Scraped', 20) RETURNING id"
            )
            bid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO builder_aliases (builder_id, alias_name) VALUES (%s, 'Never Scraped')",
                (bid,),
            )
        db_conn.commit()

        r = client.post("/builders/scrape")
        assert r.json["aliases_processed"] == 1

    def test_no_due_builders_returns_zero_stats(self, client, db_conn, clean_db):
        """No builders at all → zero everything, no error."""
        r = client.post("/builders/scrape")
        assert r.status_code == 200
        assert r.json["aliases_processed"] == 0
        assert r.json["listings_found"] == 0
