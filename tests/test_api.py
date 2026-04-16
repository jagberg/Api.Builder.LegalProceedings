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
        assert b["builderName"] == "Vogue Homes"
        assert b["isActive"] is True
        assert b["scrapeIntervalDays"] == 1
        assert set(b["aliases"]) == {"Vogue Homes", "Capitol Constructions"}
        assert b["lastScrapedAt"] is None

    def test_multiple_builders(self, client, db_conn, clean_db):
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name, scrape_interval_days) VALUES "
                "('Builder A', 1), ('Builder B', 20)"
            )
        db_conn.commit()

        r = client.get("/builders")
        assert r.status_code == 200
        names = [b["builderName"] for b in r.json["builders"]]
        assert "Builder A" in names
        assert "Builder B" in names


# ---------------------------------------------------------------------------
# GET /builders/<name>/hearings
# ---------------------------------------------------------------------------

class TestGetHearings:
    def test_unknown_builder_no_results_is_ephemeral(self, client, clean_db, mock_nsw_empty):
        """Unknown builder + no upstream results → ephemeral response, no builder created."""
        r = client.get("/builders/Nobody/hearings")
        assert r.status_code == 200
        assert r.json["ephemeral"] is True
        assert r.json["builderName"] is None
        assert r.json["hearings"] == []
        assert r.json["similarMatches"] == []
        # Builder must NOT exist
        r2 = client.get("/builders")
        names = [b["builderName"] for b in r2.json["builders"]]
        assert "Nobody" not in names

    def test_unknown_builder_with_exact_match_creates_from_trading_as(self, client, db_conn, clean_db, mock_nsw_api):
        """Exact match + 'trading as' pattern → builder created with trading-as as canonical name."""
        # MOCK_HIT parties: "John Smith v CAPITOL CONSTRUCTIONS PTY LTD trading as VOGUE HOMES NSW"
        # Searching 'Capitol Constructions' matches as a whole word.
        r = client.get("/builders/Capitol Constructions/hearings")
        assert r.status_code == 200
        assert r.json["ephemeral"] is False
        # Canonical name is the trading-as extract
        assert r.json["builderName"] == "VOGUE HOMES NSW"
        assert "Capitol Constructions" in r.json["aliases"]
        assert r.json["total"] == 1

    def test_unknown_builder_no_exact_match_returns_ephemeral_similar(self, client, clean_db, mock_nsw_api):
        """Search term with no whole-word match → ephemeral, all results in similarMatches."""
        # MOCK_HIT parties does NOT contain "Metri" as a whole word
        r = client.get("/builders/Metri/hearings")
        assert r.status_code == 200
        assert r.json["ephemeral"] is True
        assert r.json["builderName"] is None
        assert r.json["hearings"] == []
        assert len(r.json["similarMatches"]) == 1
        # Ephemeral similar matches have id=None
        assert r.json["similarMatches"][0]["id"] is None

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
        assert data["builderName"] == "Vogue Homes"
        assert data["resolvedAlias"] is False
        h = data["hearings"][0]
        assert h["externalId"] == "test001ContestedHearing"
        assert h["caseNumber"] == "2025/00100001"
        assert h["listingDate"] == "2026-04-22"
        assert h["court"] == "NCAT CCD"

    def test_alias_resolves_to_same_results(self, client, seed_listing):
        """Capitol Constructions must return identical hearings to Vogue Homes."""
        by_primary = client.get("/builders/Vogue Homes/hearings").json
        by_alias   = client.get("/builders/Capitol Constructions/hearings").json

        assert by_alias["builderName"]   == "Vogue Homes"
        assert by_alias["searchedFor"]   == "Capitol Constructions"
        assert by_alias["resolvedAlias"] is True
        assert by_alias["aliases"]       == by_primary["aliases"]
        assert by_alias["total"]         == by_primary["total"]
        assert by_alias["hearings"][0]["externalId"] == by_primary["hearings"][0]["externalId"]

    def test_response_includes_aliases_list(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings")
        assert set(r.json["aliases"]) == {"Vogue Homes", "Capitol Constructions"}

    def test_date_filter_from_date_excludes_old(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings?fromDate=2027-01-01")
        assert r.status_code == 200
        assert r.json["total"] == 0

    def test_date_filter_from_date_includes_match(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings?fromDate=2026-04-01")
        assert r.status_code == 200
        assert r.json["total"] == 1

    def test_date_filter_to_date(self, client, seed_listing):
        r = client.get("/builders/Vogue Homes/hearings?toDate=2026-04-01")
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
        assert data["builderCreated"] is False
        assert data["aliasesProcessed"] == 2   # Vogue Homes + Capitol Constructions
        assert data["listingsFound"] == 2       # one hit per alias
        assert data["listingsNew"] == 1         # same external_id → deduped on second alias

    def test_auto_creates_unknown_builder(self, client, clean_db, mock_nsw_empty):
        r = client.post("/builders/Brand New Builder/scrape")
        assert r.status_code == 201
        data = r.json
        assert data["builderCreated"] is True
        assert data["scrapeIntervalDays"] == 20
        assert data["aliasesProcessed"] == 1

    def test_auto_created_builder_appears_in_list(self, client, clean_db, mock_nsw_empty):
        client.post("/builders/Brand New Builder/scrape")
        r = client.get("/builders")
        names = [b["builderName"] for b in r.json["builders"]]
        assert "Brand New Builder" in names

    def test_auto_created_builder_has_20_day_interval(self, client, clean_db, mock_nsw_empty):
        client.post("/builders/Brand New Builder/scrape")
        r = client.get("/builders")
        b = next(b for b in r.json["builders"] if b["builderName"] == "Brand New Builder")
        assert b["scrapeIntervalDays"] == 20

    def test_scrape_writes_listings_to_db(self, client, seed_vogue, mock_nsw_api):
        client.post("/builders/Vogue Homes/scrape")
        r = client.get("/builders/Vogue Homes/hearings")
        assert r.json["total"] == 1
        assert r.json["hearings"][0]["externalId"] == "test001ContestedHearing"

    def test_scrape_idempotent(self, client, seed_vogue, mock_nsw_api):
        """Running the same scrape twice must not create duplicate listings."""
        client.post("/builders/Vogue Homes/scrape")
        r2 = client.post("/builders/Vogue Homes/scrape")
        assert r2.json["listingsNew"] == 0
        r = client.get("/builders/Vogue Homes/hearings")
        assert r.json["total"] == 1

    def test_updates_last_scraped_at(self, client, seed_vogue, mock_nsw_empty):
        client.post("/builders/Vogue Homes/scrape")
        r = client.get("/builders")
        b = next(b for b in r.json["builders"] if b["builderName"] == "Vogue Homes")
        assert b["lastScrapedAt"] is not None


# ---------------------------------------------------------------------------
# POST /builders/scrape  (all builders, due_only)
# ---------------------------------------------------------------------------

class TestScrapeAll:
    def test_scrapes_due_builders(self, client, seed_vogue, mock_nsw_api):
        r = client.post("/builders/scrape")
        assert r.status_code == 200
        assert r.json["aliasesProcessed"] == 2

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
        assert r.json["aliasesProcessed"] == 0

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
        assert r.json["aliasesProcessed"] == 1

    def test_no_due_builders_returns_zero_stats(self, client, db_conn, clean_db):
        """No builders at all → zero everything, no error."""
        r = client.post("/builders/scrape")
        assert r.status_code == 200
        assert r.json["aliasesProcessed"] == 0
        assert r.json["listingsFound"] == 0

    def test_batch_size_limits_builders(self, client, db_conn, clean_db, mock_nsw_empty):
        """batchSize caps the number of builders (not aliases) processed."""
        with db_conn.cursor() as cur:
            for name in ("Builder A", "Builder B", "Builder C"):
                cur.execute(
                    "INSERT INTO builders (builder_name, scrape_interval_days) "
                    "VALUES (%s, 1) RETURNING id", (name,),
                )
                bid = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO builder_aliases (builder_id, alias_name) VALUES (%s, %s)",
                    (bid, name),
                )
        db_conn.commit()

        r = client.post("/builders/scrape?batchSize=2")
        assert r.status_code == 200
        # 2 builders × 1 alias each = 2 aliases processed
        assert r.json["aliasesProcessed"] == 2

    def test_invalid_batch_size_returns_400(self, client, clean_db):
        r = client.post("/builders/scrape?batchSize=abc")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /builders/<id>/merge-into/<targetId>
# ---------------------------------------------------------------------------

class TestMergeBuilders:
    def test_merge_moves_aliases_and_listings(self, client, db_conn, clean_db):
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name, scrape_interval_days) "
                "VALUES ('Source Ltd', 1) RETURNING id"
            )
            source_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO builder_aliases (builder_id, alias_name) VALUES "
                "(%s, 'Source Ltd'), (%s, 'Source Alias')",
                (source_id, source_id),
            )
            cur.execute(
                "INSERT INTO builders (builder_name, scrape_interval_days) "
                "VALUES ('Target Ltd', 1) RETURNING id"
            )
            target_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO builder_aliases (builder_id, alias_name) VALUES "
                "(%s, 'Target Ltd')",
                (target_id,),
            )
        db_conn.commit()

        r = client.post(f"/builders/{source_id}/merge-into/{target_id}")
        assert r.status_code == 200
        assert r.json["aliasesMoved"] == 2  # Both source aliases non-conflicting
        assert r.json["conflictsDropped"] == 0

        # Source builder gone, target has all aliases
        r2 = client.get("/builders")
        names = [b["builderName"] for b in r2.json["builders"]]
        assert "Source Ltd" not in names
        target = next(b for b in r2.json["builders"] if b["builderName"] == "Target Ltd")
        assert set(target["aliases"]) == {"Target Ltd", "Source Ltd", "Source Alias"}

    def test_merge_moves_listings_and_similar(self, client, db_conn, clean_db):
        """Hearings and similar_matches move to the target builder."""
        with db_conn.cursor() as cur:
            cur.execute("INSERT INTO builders (builder_name) VALUES ('Src') RETURNING id")
            src = cur.fetchone()[0]
            cur.execute("INSERT INTO builders (builder_name) VALUES ('Tgt') RETURNING id")
            tgt = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO scrape_runs (status) VALUES ('success') RETURNING id"
            )
            run_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO court_listings (
                    external_id, builder_id, matched_alias, case_number, parties,
                    first_seen_run, last_seen_run
                ) VALUES ('ext1', %s, 'Src', 'C1', 'Ali v SRC PTY LTD', %s, %s)
                """,
                (src, run_id, run_id),
            )
            cur.execute(
                """
                INSERT INTO similar_matches (builder_id, searched_alias, external_id, parties)
                VALUES (%s, 'Src', 'extsim1', 'Bob v SRCX')
                """,
                (src,),
            )
        db_conn.commit()

        r = client.post(f"/builders/{src}/merge-into/{tgt}")
        assert r.status_code == 200
        assert r.json["listingsMoved"] == 1
        assert r.json["similarMoved"] == 1

        with db_conn.cursor() as cur:
            cur.execute("SELECT builder_id FROM court_listings WHERE external_id = 'ext1'")
            assert cur.fetchone()[0] == tgt
            cur.execute("SELECT builder_id FROM similar_matches WHERE external_id = 'extsim1'")
            assert cur.fetchone()[0] == tgt

    def test_merge_self_returns_400(self, client, db_conn, seed_vogue):
        r = client.post(f"/builders/{seed_vogue}/merge-into/{seed_vogue}")
        assert r.status_code == 400

    def test_merge_unknown_source_returns_404(self, client, seed_vogue):
        r = client.post(f"/builders/99999/merge-into/{seed_vogue}")
        assert r.status_code == 404

    def test_merge_unknown_target_returns_404(self, client, seed_vogue):
        r = client.post(f"/builders/{seed_vogue}/merge-into/99999")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Scrape filter: exact vs similar matches
# ---------------------------------------------------------------------------

class TestScrapeFilter:
    def test_fuzzy_match_goes_to_similar_matches(self, client, db_conn, seed_vogue, mock_nsw_fuzzy):
        """A listing whose parties don't contain the alias goes to similar_matches."""
        client.post("/builders/Vogue Homes/scrape")

        # Not in court_listings
        r = client.get("/builders/Vogue Homes/hearings")
        assert r.json["total"] == 0

        # Is in similar_matches
        with db_conn.cursor() as cur:
            cur.execute("SELECT searched_alias, reviewed FROM similar_matches")
            rows = cur.fetchall()
        assert len(rows) > 0
        assert any(row[1] is False for row in rows)  # reviewed defaults to False

    def test_exact_match_goes_to_court_listings(self, client, db_conn, seed_vogue, mock_nsw_api):
        """A listing whose parties contain the alias ends up in court_listings."""
        client.post("/builders/Vogue Homes/scrape")

        r = client.get("/builders/Vogue Homes/hearings")
        assert r.json["total"] == 1

        # Nothing in similar_matches for this listing
        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM similar_matches WHERE external_id = 'test001ContestedHearing'")
            assert cur.fetchone()[0] == 0

    def test_similar_matches_in_hearings_response(self, client, db_conn, seed_vogue, mock_nsw_fuzzy):
        """Hearings response includes unreviewed similar matches."""
        client.post("/builders/Vogue Homes/scrape")
        r = client.get("/builders/Vogue Homes/hearings")
        assert r.status_code == 200
        assert "similarMatches" in r.json
        assert len(r.json["similarMatches"]) > 0
        sm = r.json["similarMatches"][0]
        assert "id" in sm
        assert "searchedAlias" in sm
        assert "parties" in sm

    def test_similar_matches_empty_when_none(self, client, seed_vogue):
        """Hearings response returns empty similarMatches when there are none."""
        r = client.get("/builders/Vogue Homes/hearings")
        assert r.json["similarMatches"] == []


# ---------------------------------------------------------------------------
# POST /similar-matches/<id>/approve and /dismiss
# ---------------------------------------------------------------------------

class TestSimilarMatchActions:
    def _seed_similar_match(self, db_conn, builder_id):
        """Insert a similar match with raw_json and return its id."""
        import json
        raw = {
            "id": "fuzzy001",
            "scm_case_number": "2025/00999999",
            "case_title": "Jane Doe v CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD",
            "scm_dateyear": "1 May 2026",
            "time_listed": "10:00 am",
            "scm_jurisdiction_court_short": "NCAT CCD",
            "location": "NCAT Sydney (CCD)",
            "court_room_name": "Courtroom 2",
            "scm_jurisdiction_type": "NCAT",
            "jl_listing_type_ds": "Directions Hearing",
        }
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO similar_matches (builder_id, searched_alias, external_id,
                    case_number, parties, listing_date, raw_json)
                VALUES (%s, 'Capitol Constructions', 'fuzzy001',
                    '2025/00999999',
                    'Jane Doe v CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD',
                    '2026-05-01', %s)
                RETURNING id
                """,
                (builder_id, json.dumps(raw)),
            )
            match_id = cur.fetchone()[0]
        db_conn.commit()
        return match_id

    def test_approve_adds_alias_and_marks_reviewed(self, client, db_conn, seed_vogue):
        match_id = self._seed_similar_match(db_conn, seed_vogue)
        r = client.post(f"/similar-matches/{match_id}/approve")
        assert r.status_code == 200
        assert r.json["approved"] is True
        assert r.json["aliasAdded"] == "Capitol Constructions"
        assert r.json["listingCreated"] is True

        # Verify reviewed flag
        with db_conn.cursor() as cur:
            cur.execute("SELECT reviewed FROM similar_matches WHERE id = %s", (match_id,))
            assert cur.fetchone()[0] is True

    def test_approve_creates_court_listing_from_raw_json(self, client, db_conn, seed_vogue):
        """Approving a similar match re-parses raw_json into a full court listing."""
        match_id = self._seed_similar_match(db_conn, seed_vogue)
        client.post(f"/similar-matches/{match_id}/approve")

        # The listing should now appear in hearings
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT case_number, court, courtroom, listing_type "
                "FROM court_listings WHERE external_id = 'fuzzy001'"
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "2025/00999999"
        assert row[1] == "NCAT CCD"
        assert row[2] == "Courtroom 2"
        assert row[3] == "Directions Hearing"

    def test_approve_alias_appears_in_builder(self, client, db_conn, clean_db):
        """After approve, the alias shows up in GET /builders."""
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name, scrape_interval_days) "
                "VALUES ('Test Builder', 1) RETURNING id"
            )
            bid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO builder_aliases (builder_id, alias_name) VALUES (%s, 'Test Builder')",
                (bid,),
            )
            cur.execute(
                """
                INSERT INTO similar_matches (builder_id, searched_alias, external_id, parties)
                VALUES (%s, 'Test Alias', 'fuzzy002', 'Some v TEST ALIAS PTY LTD')
                RETURNING id
                """,
                (bid,),
            )
            match_id = cur.fetchone()[0]
        db_conn.commit()

        client.post(f"/similar-matches/{match_id}/approve")
        r = client.get("/builders")
        b = next(b for b in r.json["builders"] if b["builderName"] == "Test Builder")
        assert "Test Alias" in b["aliases"]

    def test_approve_already_reviewed_returns_409(self, client, db_conn, seed_vogue):
        match_id = self._seed_similar_match(db_conn, seed_vogue)
        client.post(f"/similar-matches/{match_id}/approve")
        r = client.post(f"/similar-matches/{match_id}/approve")
        assert r.status_code == 409

    def test_approve_not_found_returns_404(self, client, clean_db):
        r = client.post("/similar-matches/99999/approve")
        assert r.status_code == 404

    def test_approve_with_custom_alias(self, client, db_conn, seed_vogue):
        match_id = self._seed_similar_match(db_conn, seed_vogue)
        r = client.post(
            f"/similar-matches/{match_id}/approve",
            json={"customAlias": "Capital Constructions"},
        )
        assert r.status_code == 200
        assert r.json["aliasAdded"] == "Capital Constructions"
        r2 = client.get("/builders")
        b = next(b for b in r2.json["builders"] if b["builderName"] == "Vogue Homes")
        assert "Capital Constructions" in b["aliases"]
        assert "Capitol Constructions" in b["aliases"]  # original still there

    def test_approve_with_merge_into_builder_id(self, client, db_conn, seed_vogue):
        """mergeIntoBuilderId redirects the alias to a different builder."""
        # Create a second builder
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builders (builder_name) VALUES ('Other Builder') RETURNING id"
            )
            other_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO builder_aliases (builder_id, alias_name) VALUES (%s, 'Other Builder')",
                (other_id,),
            )
        db_conn.commit()

        match_id = self._seed_similar_match(db_conn, seed_vogue)
        r = client.post(
            f"/similar-matches/{match_id}/approve",
            json={"mergeIntoBuilderId": other_id},
        )
        assert r.status_code == 200
        assert r.json["builderId"] == other_id
        # The alias got added to the OTHER builder, not Vogue Homes
        r2 = client.get("/builders")
        other = next(b for b in r2.json["builders"] if b["builderName"] == "Other Builder")
        assert "Capitol Constructions" in other["aliases"]

    def test_approve_with_unknown_merge_target_returns_404(self, client, db_conn, seed_vogue):
        match_id = self._seed_similar_match(db_conn, seed_vogue)
        r = client.post(
            f"/similar-matches/{match_id}/approve",
            json={"mergeIntoBuilderId": 99999},
        )
        assert r.status_code == 404

    def test_dismiss_marks_reviewed(self, client, db_conn, seed_vogue):
        match_id = self._seed_similar_match(db_conn, seed_vogue)
        r = client.post(f"/similar-matches/{match_id}/dismiss")
        assert r.status_code == 200
        assert r.json["dismissed"] is True

        with db_conn.cursor() as cur:
            cur.execute("SELECT reviewed FROM similar_matches WHERE id = %s", (match_id,))
            assert cur.fetchone()[0] is True

    def test_dismiss_does_not_add_alias(self, client, db_conn, seed_vogue):
        match_id = self._seed_similar_match(db_conn, seed_vogue)
        r = client.get("/builders/Vogue Homes/hearings")
        aliases_before = set(r.json["aliases"])

        client.post(f"/similar-matches/{match_id}/dismiss")

        r = client.get("/builders/Vogue Homes/hearings")
        assert set(r.json["aliases"]) == aliases_before

    def test_dismissed_not_in_similar_matches_response(self, client, db_conn, seed_vogue):
        """After dismiss, the match no longer appears in hearings.similarMatches."""
        match_id = self._seed_similar_match(db_conn, seed_vogue)
        client.post(f"/similar-matches/{match_id}/dismiss")
        r = client.get("/builders/Vogue Homes/hearings")
        ids = [sm["id"] for sm in r.json["similarMatches"]]
        assert match_id not in ids
