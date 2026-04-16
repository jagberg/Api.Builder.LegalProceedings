"""
app.py — Flask API for the court scraper

Routes
------
GET  /builders
    List all builders with their aliases and scrape interval.

GET  /builders/<name>/hearings
    Court hearings for one builder.
    Query params (all optional):
        from_date   YYYY-MM-DD, inclusive
        to_date     YYYY-MM-DD, inclusive
        limit       default 50, max 200
        offset      default 0

POST /builders/<name>/scrape
    Trigger a scrape for one builder (all its aliases).
    If the builder name does not exist it is automatically created with a
    20-day scrape interval and its name registered as the first alias.
    Response includes builder_created: true when this happens.

POST /builders/scrape
    Trigger a scrape for every active builder that is due based on its
    scrape_interval_days — intended for the daily cron job.
    Builders with a 20-day interval are skipped unless 20 days have passed
    since their last_scraped_at.
"""

import logging
import sys
from urllib.parse import unquote

import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from scraper.client import RegistryClient, parse_listing
from scraper.db import (
    create_builder,
    fetch_active_aliases,
    get_connection,
    insert_similar_match,
)
from scraper.main import run
from scraper.matching import alias_matches_parties
from scraper.parties import extract_short_name_before_trading_as, extract_trading_name

load_dotenv()

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Map snake_case keys returned by scraper.main.run() to the camelCase form
# used on the API surface. Keys not in this map pass through unchanged.
_RUN_RESULT_KEY_MAP = {
    "run_id":            "runId",
    "aliases_processed": "aliasesProcessed",
    "listings_found":    "listingsFound",
    "listings_new":      "listingsNew",
    "error_message":     "errorMessage",
}


def _camelize_run_result(result: dict) -> dict:
    """Transform scraper.main.run() dict keys to camelCase for JSON output."""
    return {_RUN_RESULT_KEY_MAP.get(k, k): v for k, v in result.items()}


def _live_search(term: str) -> list[dict]:
    """Call the NSW registry API for `term`. Return a list of raw hit dicts."""
    try:
        client_api = RegistryClient()
        return list(client_api.search(term))
    except Exception as exc:
        logger.error(f"Live search failed for {term!r}: {exc}")
        return []


def _split_exact_vs_fuzzy(term: str, raw_hits: list[dict]) -> tuple[list, list]:
    """Split raw hits into (exact, fuzzy) by word-boundary match against parties."""
    exact, fuzzy = [], []
    for raw in raw_hits:
        listing = parse_listing(raw)
        if not listing["external_id"]:
            continue
        if alias_matches_parties(term, listing["parties"]):
            exact.append(listing)
        else:
            fuzzy.append(listing)
    return exact, fuzzy


def _hit_to_similar_match_dict(listing: dict) -> dict:
    """Shape an (unpersisted) listing as a SimilarMatch for the ephemeral path."""
    return {
        "id":            None,   # no DB id — ephemeral
        "searchedAlias": None,
        "externalId":    listing["external_id"],
        "caseNumber":    listing.get("case_number"),
        "parties":       listing.get("parties"),
        "listingDate":   str(listing["listing_date"]) if listing.get("listing_date") else None,
        "createdAt":     None,
    }


def _ephemeral_response(searched_for: str, fuzzy_hits: list, limit: int, offset: int) -> dict:
    """Build the response for a search that didn't match any builder exactly."""
    return {
        "builderName":    None,
        "searchedFor":    searched_for,
        "resolvedAlias":  False,
        "ephemeral":      True,
        "aliases":        [],
        "total":          0,
        "offset":         offset,
        "limit":          limit,
        "hearings":       [],
        "similarMatches": [_hit_to_similar_match_dict(l) for l in fuzzy_hits],
    }


def _create_or_find_builder_for_search(conn, searched_for: str, exact_hits: list) -> dict:
    """
    Create a builder for a new search with exact matches, or find and reuse an
    existing one when the extracted trading-as name already exists.
    Adds the searched_for term and (when found) the short trading-as name as aliases.
    """
    # Prefer the trading-as name from the first exact hit
    first_parties = exact_hits[0].get("parties")
    trading_name = extract_trading_name(first_parties)
    short_name   = extract_short_name_before_trading_as(first_parties)

    canonical = trading_name or searched_for

    existing = _find_builder_by_name_or_alias(conn, canonical)
    if existing:
        # Merge new search into existing builder
        _ensure_alias(conn, existing["id"], searched_for)
        if short_name and short_name != canonical:
            _ensure_alias(conn, existing["id"], short_name)
        logger.info(
            f"Reused existing builder {canonical!r} for search {searched_for!r}"
        )
        return existing

    # Create a new builder with the trading-as name as canonical
    create_builder(conn, canonical, scrape_interval_days=20)
    new_builder = _find_builder_by_name_or_alias(conn, canonical)
    if searched_for != canonical:
        _ensure_alias(conn, new_builder["id"], searched_for)
    if short_name and short_name != canonical and short_name != searched_for:
        _ensure_alias(conn, new_builder["id"], short_name)
    logger.info(
        f"Created builder {canonical!r} from search {searched_for!r}"
    )
    return new_builder


def _persist_hits(conn, builder_id: int, searched_for: str,
                  exact_hits: list, fuzzy_hits: list) -> None:
    """
    Persist exact hits as court_listings and fuzzy hits as similar_matches.
    Uses a fresh scrape_run for traceability.
    """
    from scraper.db import start_run, finish_run, upsert_listing, update_builders_last_scraped

    run_id = start_run(conn)
    inserted = 0
    try:
        for listing in exact_hits:
            is_new = upsert_listing(conn, builder_id, searched_for, run_id, listing)
            if is_new:
                inserted += 1
        for listing in fuzzy_hits:
            insert_similar_match(conn, builder_id, searched_for, listing)
        finish_run(conn, run_id, "success",
                   aliases_processed=1,
                   listings_found=len(exact_hits) + len(fuzzy_hits),
                   listings_new=inserted)
        update_builders_last_scraped(conn, {builder_id})
    except Exception as exc:
        logger.exception("Persist failed")
        finish_run(conn, run_id, "failed", 1, 0, 0, str(exc))


def _find_builder_by_name_or_alias(conn, name: str) -> dict | None:
    """Return {id, builder_name} for a builder matching name (canonical or alias)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT DISTINCT b.id, b.builder_name
              FROM builders b
         LEFT JOIN builder_aliases ba ON ba.builder_id = b.id
             WHERE b.is_active = 1
               AND (b.builder_name = %s OR ba.alias_name = %s)
            """,
            (name, name),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _ensure_alias(conn, builder_id: int, alias_name: str) -> None:
    """Add an alias to a builder, no-op if it already exists."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO builder_aliases (builder_id, alias_name)
            VALUES (%s, %s)
            ON CONFLICT (alias_name) DO NOTHING
            """,
            (builder_id, alias_name),
        )
    conn.commit()


def _get_builder_aliases(conn, builder_name: str) -> list | None:
    """
    Return aliases for a builder, or None if the builder does not exist /
    is inactive.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id FROM builders WHERE builder_name = %s AND is_active = 1",
            (builder_name,),
        )
        builder = cur.fetchone()

    if not builder:
        return None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT ba.id  AS alias_id,
                   b.id   AS builder_id,
                   b.builder_name,
                   ba.alias_name
              FROM builder_aliases ba
              JOIN builders b ON ba.builder_id = b.id
             WHERE b.id = %s
             ORDER BY ba.id
            """,
            (builder["id"],),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# GET /builders
# ---------------------------------------------------------------------------

@app.route("/builders", methods=["GET"])
def list_builders():
    try:
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT b.id,
                           b.builder_name,
                           b.is_active,
                           b.scrape_interval_days,
                           b.last_scraped_at,
                           COALESCE(
                               json_agg(ba.alias_name ORDER BY ba.id)
                               FILTER (WHERE ba.alias_name IS NOT NULL),
                               '[]'
                           ) AS aliases
                      FROM builders b
                 LEFT JOIN builder_aliases ba ON ba.builder_id = b.id
                  GROUP BY b.id
                  ORDER BY b.builder_name
                    """
                )
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("DB query failed")
        return jsonify({"error": str(exc)}), 500

    builders = [
        {
            "id":                 row["id"],
            "builderName":        row["builder_name"],
            "isActive":           bool(row["is_active"]),
            "scrapeIntervalDays": row["scrape_interval_days"],
            "lastScrapedAt":      str(row["last_scraped_at"]) if row["last_scraped_at"] else None,
            "aliases":            row["aliases"],
        }
        for row in rows
    ]
    return jsonify({"builders": builders}), 200


# ---------------------------------------------------------------------------
# GET /builders/<name>/hearings
# ---------------------------------------------------------------------------

@app.route("/builders/<path:name>/hearings", methods=["GET"])
def get_hearings(name: str):
    searched_for = unquote(name)
    from_date    = request.args.get("fromDate")
    to_date      = request.args.get("toDate")

    try:
        limit  = min(int(request.args.get("limit",  50)), 200)
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400

    try:
        conn = get_connection()
        try:
            builder = _find_builder_by_name_or_alias(conn, searched_for)

            if builder:
                # Scenario 3 — existing builder. Scrape for fresh data, then return.
                # Skip scraping in test mode to keep tests fast and deterministic.
                if not app.config.get("TESTING"):
                    aliases_list = _get_builder_aliases(conn, builder["builder_name"])
                    conn.close()
                    try:
                        run(aliases=aliases_list)
                    except Exception as exc:
                        logger.error(f"Refresh scrape failed for {searched_for!r}: {exc}")
                    conn = get_connection()
                ephemeral = False
            else:
                # Live search against NSW registry. Routing depends on whether
                # any result contains the search term as a whole word.
                raw_hits = _live_search(searched_for)
                exact_hits, fuzzy_hits = _split_exact_vs_fuzzy(searched_for, raw_hits)

                if not exact_hits:
                    # Scenario 2 — no persistence. Return ephemeral preview.
                    return jsonify(
                        _ephemeral_response(searched_for, fuzzy_hits, limit, offset)
                    ), 200

                # Scenario 1 — exact matches exist. Create or merge into a builder.
                builder = _create_or_find_builder_for_search(
                    conn, searched_for, exact_hits,
                )
                _persist_hits(conn, builder["id"], searched_for, exact_hits, fuzzy_hits)
                ephemeral = False

            builder_id   = builder["id"]
            builder_name = builder["builder_name"]

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT alias_name FROM builder_aliases WHERE builder_id = %s ORDER BY id",
                    (builder_id,),
                )
                aliases = [row[0] for row in cur.fetchall()]

            conditions = ["cl.is_active = 1", "cl.builder_id = %s"]
            params: list = [builder_id]

            if from_date:
                conditions.append("cl.listing_date >= %s")
                params.append(from_date)
            if to_date:
                conditions.append("cl.listing_date <= %s")
                params.append(to_date)

            where = " AND ".join(conditions)

            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM court_listings cl WHERE {where}",
                    params,
                )
                total = cur.fetchone()[0]

            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT cl.external_id,
                           cl.matched_alias,
                           cl.case_number,
                           cl.parties,
                           cl.listing_date,
                           cl.listing_time,
                           cl.court,
                           cl.location,
                           cl.courtroom,
                           cl.jurisdiction,
                           cl.listing_type,
                           cl.presiding_officer,
                           cl.created_at,
                           cl.updated_at
                      FROM court_listings cl
                     WHERE {where}
                     ORDER BY cl.listing_date ASC, cl.listing_time ASC NULLS LAST
                     LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                rows = cur.fetchall()

            # Unreviewed similar matches for this builder
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT sm.id, sm.searched_alias, sm.external_id,
                           sm.case_number, sm.parties, sm.listing_date,
                           sm.created_at
                      FROM similar_matches sm
                     WHERE sm.builder_id = %s AND sm.reviewed = FALSE
                     ORDER BY sm.listing_date ASC NULLS LAST, sm.created_at DESC
                    """,
                    (builder_id,),
                )
                similar_rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("DB query failed")
        return jsonify({"error": str(exc)}), 500

    hearings = []
    for row in rows:
        d = dict(row)
        hearings.append({
            "externalId":       d["external_id"],
            "matchedAlias":     d["matched_alias"],
            "caseNumber":       d["case_number"],
            "parties":          d["parties"],
            "listingDate":      str(d["listing_date"]) if d["listing_date"] is not None else None,
            "listingTime":      str(d["listing_time"]) if d["listing_time"] is not None else None,
            "court":            d["court"],
            "location":         d["location"],
            "courtroom":        d["courtroom"],
            "jurisdiction":     d["jurisdiction"],
            "listingType":      d["listing_type"],
            "presidingOfficer": d["presiding_officer"],
            "createdAt":        str(d["created_at"]) if d["created_at"] is not None else None,
            "updatedAt":        str(d["updated_at"]) if d["updated_at"] is not None else None,
        })

    similar_matches = []
    for row in similar_rows:
        d = dict(row)
        similar_matches.append({
            "id":             d["id"],
            "searchedAlias":  d["searched_alias"],
            "externalId":     d["external_id"],
            "caseNumber":     d["case_number"],
            "parties":        d["parties"],
            "listingDate":    str(d["listing_date"]) if d["listing_date"] is not None else None,
            "createdAt":      str(d["created_at"]) if d["created_at"] is not None else None,
        })

    return jsonify({
        "builderName":    builder_name,
        "searchedFor":    searched_for,
        "resolvedAlias":  searched_for != builder_name,
        "ephemeral":      ephemeral,
        "aliases":        aliases,
        "total":          total,
        "offset":         offset,
        "limit":          limit,
        "hearings":       hearings,
        "similarMatches": similar_matches,
    }), 200


# ---------------------------------------------------------------------------
# POST /builders/scrape  — scrape ALL due builders (daily cron target)
# Registered before <name>/scrape so Flask matches 'scrape' literally.
# ---------------------------------------------------------------------------

@app.route("/builders/scrape", methods=["POST"])
def scrape_all():
    # batchSize caps the number of BUILDERS scraped per call — staggering load
    # across frequent cron invocations. All aliases of each selected builder
    # are processed atomically.
    batch_size: int | None
    try:
        raw_batch = request.args.get("batchSize")
        batch_size = int(raw_batch) if raw_batch else None
    except ValueError:
        return jsonify({"error": "batchSize must be an integer"}), 400

    try:
        conn = get_connection()
        try:
            aliases = fetch_active_aliases(conn, due_only=True, batch_size=batch_size)
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("DB connection failed")
        return jsonify({"error": str(exc)}), 500

    logger.info(f"/builders/scrape: {len(aliases)} alias(es) due for scraping "
                f"(batchSize={batch_size})")

    try:
        result = run(aliases=aliases)
    except Exception as exc:
        logger.exception("Scrape failed")
        return jsonify({"error": str(exc)}), 500

    return jsonify(_camelize_run_result(result)), 200


# ---------------------------------------------------------------------------
# POST /builders/<name>/scrape  — scrape one builder
# Auto-creates the builder with a 20-day interval if it doesn't exist.
# ---------------------------------------------------------------------------

@app.route("/builders/<path:name>/scrape", methods=["POST"])
def scrape_builder(name: str):
    builder_name = unquote(name)
    builder_created = False

    try:
        conn = get_connection()
        try:
            aliases = _get_builder_aliases(conn, builder_name)
            if aliases is None:
                # Auto-create with 20-day scrape interval
                create_builder(conn, builder_name, scrape_interval_days=20)
                aliases = _get_builder_aliases(conn, builder_name)
                builder_created = True
                logger.info(
                    f"Auto-created builder {builder_name!r} "
                    f"with scrape_interval_days=20"
                )
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("DB connection failed")
        return jsonify({"error": str(exc)}), 500

    try:
        result = run(aliases=aliases)
    except Exception as exc:
        logger.exception("Scrape failed")
        return jsonify({"error": str(exc)}), 500

    out = _camelize_run_result(result)
    out["builderCreated"]     = builder_created
    out["scrapeIntervalDays"] = 20 if builder_created else 1

    return jsonify(out), 201 if builder_created else 200


# ---------------------------------------------------------------------------
# POST /similar-matches/<id>/approve — add alias + mark reviewed
# ---------------------------------------------------------------------------

@app.route("/similar-matches/<int:match_id>/approve", methods=["POST"])
def approve_similar(match_id: int):
    from scraper.db import start_run, finish_run, upsert_listing

    body = request.get_json(silent=True) or {}
    custom_alias   = body.get("customAlias")
    merge_target   = body.get("mergeIntoBuilderId")

    try:
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, builder_id, searched_alias, external_id, "
                    "       raw_json, reviewed "
                    "FROM similar_matches WHERE id = %s",
                    (match_id,),
                )
                match = cur.fetchone()

            if not match:
                return jsonify({"error": f"Similar match not found: {match_id}"}), 404

            if match["reviewed"]:
                return jsonify({"error": "Already reviewed"}), 409

            target_builder_id = merge_target if merge_target else match["builder_id"]
            alias_name        = custom_alias or match["searched_alias"]

            # Verify target builder exists
            if merge_target:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM builders WHERE id = %s", (merge_target,))
                    if cur.fetchone() is None:
                        return jsonify({"error": f"Target builder not found: {merge_target}"}), 404

            with conn.cursor() as cur:
                # Upsert alias — moves it to the target builder if it exists elsewhere.
                cur.execute(
                    """
                    INSERT INTO builder_aliases (builder_id, alias_name)
                    VALUES (%s, %s)
                    ON CONFLICT (alias_name) DO UPDATE
                        SET builder_id = EXCLUDED.builder_id
                    """,
                    (target_builder_id, alias_name),
                )
                cur.execute(
                    "UPDATE similar_matches SET reviewed = TRUE WHERE id = %s",
                    (match_id,),
                )
            conn.commit()

            # Re-parse raw_json and insert into court_listings so the
            # hearing data is immediately available in the hearings list.
            listing_created = False
            if match["raw_json"]:
                raw = match["raw_json"]
                if isinstance(raw, str):
                    import json
                    raw = json.loads(raw)
                listing = parse_listing(raw)
                if listing["external_id"]:
                    run_id = start_run(conn)
                    is_new = upsert_listing(
                        conn, target_builder_id, alias_name, run_id, listing,
                    )
                    finish_run(conn, run_id, "success", 0, 1, 1 if is_new else 0)
                    listing_created = is_new
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("Approve failed")
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "id":             match_id,
        "approved":       True,
        "aliasAdded":     alias_name,
        "builderId":      target_builder_id,
        "listingCreated": listing_created,
    }), 200


# ---------------------------------------------------------------------------
# POST /similar-matches/<id>/dismiss — mark reviewed without adding alias
# ---------------------------------------------------------------------------

@app.route("/similar-matches/<int:match_id>/dismiss", methods=["POST"])
def dismiss_similar(match_id: int):
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE similar_matches SET reviewed = TRUE WHERE id = %s AND reviewed = FALSE",
                    (match_id,),
                )
                updated = cur.rowcount
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("Dismiss failed")
        return jsonify({"error": str(exc)}), 500

    if updated == 0:
        return jsonify({"error": f"Similar match not found or already reviewed: {match_id}"}), 404

    return jsonify({"id": match_id, "dismissed": True}), 200


# ---------------------------------------------------------------------------
# POST /builders/<id>/merge-into/<targetId> — merge one builder into another
# Silent dedupe on conflicting aliases (target wins).
# ---------------------------------------------------------------------------

@app.route("/builders/<int:source_id>/merge-into/<int:target_id>", methods=["POST"])
def merge_builders(source_id: int, target_id: int):
    if source_id == target_id:
        return jsonify({"error": "Cannot merge a builder into itself"}), 400

    try:
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, builder_name FROM builders WHERE id IN (%s, %s)",
                    (source_id, target_id),
                )
                rows = {row["id"]: row for row in cur.fetchall()}

            if source_id not in rows:
                return jsonify({"error": f"Source builder not found: {source_id}"}), 404
            if target_id not in rows:
                return jsonify({"error": f"Target builder not found: {target_id}"}), 404

            with conn.cursor() as cur:
                # Delete source aliases that would conflict with target aliases
                cur.execute(
                    """
                    DELETE FROM builder_aliases
                     WHERE builder_id = %s
                       AND alias_name IN (
                           SELECT alias_name FROM builder_aliases WHERE builder_id = %s
                       )
                    """,
                    (source_id, target_id),
                )
                conflicts_dropped = cur.rowcount

                # Move remaining aliases to target
                cur.execute(
                    "UPDATE builder_aliases SET builder_id = %s WHERE builder_id = %s",
                    (target_id, source_id),
                )
                aliases_moved = cur.rowcount

                # Move listings and similar matches (external_id is globally unique,
                # so no in-table conflicts possible)
                cur.execute(
                    "UPDATE court_listings SET builder_id = %s WHERE builder_id = %s",
                    (target_id, source_id),
                )
                listings_moved = cur.rowcount

                cur.execute(
                    "UPDATE similar_matches SET builder_id = %s WHERE builder_id = %s",
                    (target_id, source_id),
                )
                similar_moved = cur.rowcount

                cur.execute("DELETE FROM builders WHERE id = %s", (source_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("Merge failed")
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "sourceId":         source_id,
        "targetId":         target_id,
        "targetName":       rows[target_id]["builder_name"],
        "aliasesMoved":     aliases_moved,
        "conflictsDropped": conflicts_dropped,
        "listingsMoved":    listings_moved,
        "similarMoved":     similar_moved,
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
