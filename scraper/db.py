"""
db.py — PostgreSQL connection and query helpers
"""
import json
import logging
import os

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=10,
    )


def fetch_active_aliases(conn, due_only: bool = False) -> list[dict]:
    """
    Return aliases for all active builders.

    due_only=True  — only include builders whose last_scraped_at is older than
                     their scrape_interval_days, or who have never been scraped.
                     Used by the daily cron so infrequent builders are skipped.
    due_only=False — return all active aliases regardless of interval (default).
    """
    due_filter = """
        AND (
            b.last_scraped_at IS NULL
            OR b.last_scraped_at < NOW() - (b.scrape_interval_days || ' days')::INTERVAL
        )
    """ if due_only else ""

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT ba.id  AS alias_id,
                   b.id   AS builder_id,
                   b.builder_name,
                   ba.alias_name
              FROM builder_aliases ba
              JOIN builders b ON ba.builder_id = b.id
             WHERE b.is_active = 1
             {due_filter}
             ORDER BY b.id, ba.id
            """
        )
        return [dict(row) for row in cur.fetchall()]


def create_builder(conn, builder_name: str, scrape_interval_days: int = 20) -> dict:
    """
    Insert a new builder and add its name as the first alias.
    Returns the new builder row as a dict.
    Safe to call if the builder already exists (no-op on conflict).
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO builders (builder_name, scrape_interval_days)
            VALUES (%s, %s)
            ON CONFLICT (builder_name) DO NOTHING
            RETURNING id, builder_name, scrape_interval_days
            """,
            (builder_name, scrape_interval_days),
        )
        builder = cur.fetchone()

        if builder is None:
            # Already existed — fetch it
            cur.execute(
                "SELECT id, builder_name, scrape_interval_days FROM builders WHERE builder_name = %s",
                (builder_name,),
            )
            builder = cur.fetchone()

        cur.execute(
            """
            INSERT INTO builder_aliases (builder_id, alias_name)
            VALUES (%s, %s)
            ON CONFLICT (alias_name) DO NOTHING
            """,
            (builder["id"], builder_name),
        )

    conn.commit()
    return dict(builder)


def update_builders_last_scraped(conn, builder_ids: set) -> None:
    """Mark a set of builders as scraped right now."""
    if not builder_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE builders SET last_scraped_at = NOW() WHERE id = ANY(%s)",
            (list(builder_ids),),
        )
    conn.commit()


def start_run(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scrape_runs (status) VALUES ('running') RETURNING id"
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    logger.info(f"Started scrape run id={run_id}")
    return run_id


def finish_run(conn, run_id: int, status: str, aliases_processed: int,
               listings_found: int, listings_new: int, error_message: str | None = None):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scrape_runs
               SET finished_at       = NOW(),
                   status            = %s,
                   aliases_processed = %s,
                   listings_found    = %s,
                   listings_new      = %s,
                   error_message     = %s
             WHERE id = %s
            """,
            (status, aliases_processed, listings_found, listings_new, error_message, run_id),
        )
    conn.commit()


def upsert_listing(conn, builder_id: int, matched_alias: str, run_id: int,
                   listing: dict) -> bool:
    """
    Insert or update a court listing.
    Returns True if this is a new record, False if updated.

    xmax = 0 on a just-written row means it was inserted, not updated —
    the standard PostgreSQL idiom inside ON CONFLICT DO UPDATE.
    """
    sql = """
        INSERT INTO court_listings (
            external_id, builder_id, matched_alias,
            case_number, parties,
            listing_date, listing_time,
            court, location, courtroom,
            jurisdiction, listing_type, presiding_officer,
            raw_json, first_seen_run, last_seen_run
        ) VALUES (
            %(external_id)s, %(builder_id)s, %(matched_alias)s,
            %(case_number)s, %(parties)s,
            %(listing_date)s, %(listing_time)s,
            %(court)s, %(location)s, %(courtroom)s,
            %(jurisdiction)s, %(listing_type)s, %(presiding_officer)s,
            %(raw_json)s, %(run_id)s, %(run_id)s
        )
        ON CONFLICT (external_id) DO UPDATE SET
            last_seen_run     = EXCLUDED.last_seen_run,
            listing_date      = EXCLUDED.listing_date,
            listing_time      = EXCLUDED.listing_time,
            court             = EXCLUDED.court,
            location          = EXCLUDED.location,
            courtroom         = EXCLUDED.courtroom,
            listing_type      = EXCLUDED.listing_type,
            presiding_officer = EXCLUDED.presiding_officer,
            raw_json          = EXCLUDED.raw_json,
            is_active         = 1
        RETURNING (xmax = 0) AS inserted
    """
    params = {
        **listing,
        "builder_id":    builder_id,
        "matched_alias": matched_alias,
        "run_id":        run_id,
        "raw_json":      json.dumps(listing.get("raw_json", {})),
    }

    with conn.cursor() as cur:
        cur.execute(sql, params)
        is_new = cur.fetchone()[0]
    conn.commit()
    return bool(is_new)


def insert_similar_match(conn, builder_id: int, searched_alias: str,
                         listing: dict) -> bool:
    """
    Record a listing that the upstream API returned but that didn't exactly
    match the searched alias.  ON CONFLICT DO NOTHING keeps it idempotent.
    Returns True if a row was actually inserted.
    """
    sql = """
        INSERT INTO similar_matches (
            builder_id, searched_alias, external_id,
            case_number, parties, listing_date, raw_json
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (external_id, searched_alias) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql, (
            builder_id,
            searched_alias,
            listing["external_id"],
            listing.get("case_number"),
            listing.get("parties"),
            listing.get("listing_date"),
            json.dumps(listing.get("raw_json", {})),
        ))
        inserted = cur.rowcount == 1
    conn.commit()
    return inserted
