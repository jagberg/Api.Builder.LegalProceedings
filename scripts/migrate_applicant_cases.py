"""
migrate_applicant_cases.py

Scans similar_matches for rows where the builder is the applicant (before "v")
and promotes them into court_listings with builder_is_applicant=TRUE.

Run once after deploying the builder_is_applicant column:

    py -3 scripts/migrate_applicant_cases.py

Rows are NOT removed from similar_matches — they remain for audit.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

from scraper.client import parse_listing
from scraper.db import upsert_listing
from scraper.matching import alias_match_side


def main():
    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )

    with conn.cursor() as cur:
        cur.execute("INSERT INTO scrape_runs (status) VALUES ('success') RETURNING id")
        migration_run_id = cur.fetchone()[0]
    conn.commit()

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT builder_id, searched_alias, raw_json FROM similar_matches")
        rows = cur.fetchall()

    moved = 0
    skipped = 0
    for row in rows:
        listing = parse_listing(row["raw_json"])
        if alias_match_side(row["searched_alias"], listing["parties"]) == "applicant":
            upsert_listing(
                conn,
                row["builder_id"],
                row["searched_alias"],
                migration_run_id,
                listing,
                builder_is_applicant=True,
            )
            moved += 1
        else:
            skipped += 1

    conn.close()
    print(f"Done. Promoted {moved} applicant cases → court_listings. Skipped {skipped} rows.")


if __name__ == "__main__":
    main()
