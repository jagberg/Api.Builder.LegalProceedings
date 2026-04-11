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
            "id":                   row["id"],
            "builder_name":         row["builder_name"],
            "is_active":            bool(row["is_active"]),
            "scrape_interval_days": row["scrape_interval_days"],
            "last_scraped_at":      str(row["last_scraped_at"]) if row["last_scraped_at"] else None,
            "aliases":              row["aliases"],
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
    from_date    = request.args.get("from_date")
    to_date      = request.args.get("to_date")

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
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("DB query failed")
        return jsonify({"error": str(exc)}), 500

    hearings = []
    for row in rows:
        d = dict(row)
        for key in ("listing_date", "listing_time", "created_at", "updated_at"):
            if d[key] is not None:
                d[key] = str(d[key])
        hearings.append(d)

    return jsonify({
        "builder_name":   builder_name,
        "searched_for":   searched_for,
        "resolved_alias": searched_for != builder_name,
        "aliases":        aliases,
        "total":          total,
        "offset":         offset,
        "limit":          limit,
        "hearings":       hearings,
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

    return jsonify(result), 200


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

    result["builder_created"]     = builder_created
    result["scrape_interval_days"] = 20 if builder_created else 1

    return jsonify(result), 201 if builder_created else 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
