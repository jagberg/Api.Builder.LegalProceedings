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

from scraper.db import (
    create_builder,
    fetch_active_aliases,
    get_connection,
)
from scraper.main import run

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

    # ------------------------------------------------------------------
    # Resolve the name against both primary builder names and aliases.
    # "Capitol Constructions" and "Vogue Homes" both resolve to the same
    # builder_id so their hearings are always returned together.
    # ------------------------------------------------------------------
    try:
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT DISTINCT b.id, b.builder_name
                      FROM builders b
                 LEFT JOIN builder_aliases ba ON ba.builder_id = b.id
                     WHERE b.is_active = 1
                       AND (b.builder_name = %s OR ba.alias_name = %s)
                    """,
                    (searched_for, searched_for),
                )
                builder = cur.fetchone()

            if not builder:
                return jsonify({"error": f"Builder not found: {searched_for}"}), 404

            builder_id   = builder["id"]
            builder_name = builder["builder_name"]   # canonical primary name

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
    try:
        conn = get_connection()
        try:
            # due_only=True: skips builders whose interval hasn't elapsed yet
            aliases = fetch_active_aliases(conn, due_only=True)
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("DB connection failed")
        return jsonify({"error": str(exc)}), 500

    logger.info(f"/builders/scrape: {len(aliases)} alias(es) due for scraping")

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
    try:
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, builder_id, searched_alias, reviewed "
                    "FROM similar_matches WHERE id = %s",
                    (match_id,),
                )
                match = cur.fetchone()

            if not match:
                return jsonify({"error": f"Similar match not found: {match_id}"}), 404

            if match["reviewed"]:
                return jsonify({"error": "Already reviewed"}), 409

            # Add the searched alias as a new builder alias
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO builder_aliases (builder_id, alias_name)
                    VALUES (%s, %s)
                    ON CONFLICT (alias_name) DO NOTHING
                    """,
                    (match["builder_id"], match["searched_alias"]),
                )
                cur.execute(
                    "UPDATE similar_matches SET reviewed = TRUE WHERE id = %s",
                    (match_id,),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("Approve failed")
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "id":       match_id,
        "approved": True,
        "aliasAdded": match["searched_alias"],
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
