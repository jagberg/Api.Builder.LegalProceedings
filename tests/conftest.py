"""
conftest.py — shared fixtures for all integration tests.

Requires the PostgreSQL container to be running:
    docker compose up -d db

Tests use the same database as local dev. Every test that touches the DB
runs inside the clean_db fixture which truncates all tables before each test.
"""

import os
from unittest.mock import Mock, patch

import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Sample NSW API response — mirrors the confirmed live payload shape
# ---------------------------------------------------------------------------
MOCK_HIT = {
    "id": "test001ContestedHearing",
    "scm_case_number": "2025/00100001",
    "case_title": "John Smith v VOGUE HOMES NSW PTY LTD",
    "scm_dateyear": "22 Apr 2026",
    "time_listed": "9:15 am",
    "scm_jurisdiction_court_short": "NCAT CCD",
    "location": "NCAT Liverpool (CCD)",
    "court_room_name": "Courtroom 3",
    "scm_jurisdiction_type": "NCAT",
    "jl_listing_type_ds": "Contested Hearing",
}

MOCK_NSW_RESPONSE = {"hits": [MOCK_HIT], "total": 1, "offset": 0, "count": 30}
MOCK_NSW_EMPTY    = {"hits": [],          "total": 0, "offset": 0, "count": 30}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_conn():
    """Single DB connection shared across the test session."""
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ.get("DB_NAME", "court_scraper"),
        user=os.environ.get("DB_USER", "scraper_user"),
        password=os.environ.get("DB_PASSWORD", ""),
        connect_timeout=5,
    )
    yield conn
    conn.close()


@pytest.fixture()
def clean_db(db_conn):
    """Wipe all data tables before each test that requests this fixture."""
    db_conn.rollback()   # clear any aborted transaction from a previous test
    with db_conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE court_listings, scrape_runs, builder_aliases, builders
            RESTART IDENTITY CASCADE
            """
        )
    db_conn.commit()


@pytest.fixture()
def seed_vogue(db_conn, clean_db):
    """
    Seed the canonical test builder: Vogue Homes with two aliases.
    Returns the builder_id.
    """
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO builders (builder_name, scrape_interval_days) "
            "VALUES ('Vogue Homes', 1) RETURNING id"
        )
        builder_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO builder_aliases (builder_id, alias_name) VALUES "
            "(%s, 'Vogue Homes'), (%s, 'Capitol Constructions')",
            (builder_id, builder_id),
        )
    db_conn.commit()
    return builder_id


@pytest.fixture()
def seed_listing(db_conn, seed_vogue):
    """
    Seed one court listing for Vogue Homes so GET /hearings has data to return.
    Returns the external_id.
    """
    import json

    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scrape_runs (status) VALUES ('success') RETURNING id"
        )
        run_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO court_listings (
                external_id, builder_id, matched_alias,
                case_number, parties, listing_date, listing_time,
                court, location, courtroom, jurisdiction, listing_type,
                raw_json, first_seen_run, last_seen_run
            ) VALUES (
                'test001ContestedHearing', %s, 'Capitol Constructions',
                '2025/00100001', 'John Smith v VOGUE HOMES NSW PTY LTD',
                '2026-04-22', '09:15:00',
                'NCAT CCD', 'NCAT Liverpool (CCD)', 'Courtroom 3',
                'NCAT', 'Contested Hearing',
                %s, %s, %s
            )
            """,
            (seed_vogue, json.dumps(MOCK_HIT), run_id, run_id),
        )
    db_conn.commit()
    return "test001ContestedHearing"


# ---------------------------------------------------------------------------
# Flask test client
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    import app as flask_app
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# NSW API mock — patches at the HTTP layer so the full client stack runs
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_nsw_api():
    """Patch requests.Session.get to return a single mock listing."""
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_NSW_RESPONSE
    with patch("requests.Session.get", return_value=mock_resp):
        yield


@pytest.fixture()
def mock_nsw_empty():
    """Patch requests.Session.get to return zero results."""
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_NSW_EMPTY
    with patch("requests.Session.get", return_value=mock_resp):
        yield
