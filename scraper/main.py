"""
main.py — orchestrates the scraper run

Usage:
    python -m scraper.main                    # scrape all active aliases
    python -m scraper.main --dry-run          # fetch but don't write to DB
    python -m scraper.main --debug            # verbose logging
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from scraper.client import RegistryClient, parse_listing
from scraper.db import (
    get_connection,
    fetch_active_aliases,
    start_run,
    finish_run,
    update_builders_last_scraped,
    upsert_listing,
)

load_dotenv()


def configure_logging(debug: bool):
    level = logging.DEBUG if debug else getattr(
        logging, os.environ.get("SCRAPER_LOG_LEVEL", "INFO").upper(), logging.INFO
    )
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler("/app/logs/scraper.log", encoding="utf-8"))
    except OSError:
        pass  # log file path unavailable outside Docker

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=handlers,
    )


def run(dry_run: bool = False, aliases: list[dict] | None = None) -> dict:
    """
    Execute a scrape run.

    Args:
        dry_run: Fetch data but don't write to DB.
        aliases: Optional pre-filtered list of alias dicts
                 (builder_id, builder_name, alias_name).
                 If None, all active aliases are fetched from the DB.

    Returns:
        dict with run_id, status, aliases_processed, listings_found, listings_new.
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Starting court scraper (dry_run={dry_run})")

    need_conn = (aliases is None) or (not dry_run)
    conn = get_connection() if need_conn else None

    if aliases is None:
        aliases = fetch_active_aliases(conn)

    logger.info(f"Found {len(aliases)} alias(es) to scrape")

    run_id = None if dry_run else start_run(conn)
    client = RegistryClient()

    total_listings_found = 0
    total_listings_new   = 0
    aliases_processed    = 0
    overall_status       = "success"
    processed_builder_ids: set[int] = set()

    for alias in aliases:
        builder_id   = alias["builder_id"]
        builder_name = alias["builder_name"]
        alias_name   = alias["alias_name"]
        logger.info(f"Scraping alias {alias_name!r} (builder: {builder_name})")

        listings_found = 0
        listings_new   = 0
        error_msg      = None

        try:
            for raw in client.search(alias_name):
                listings_found += 1
                listing = parse_listing(raw)

                if not listing["external_id"]:
                    logger.warning(f"Listing missing external_id, skipping: {raw}")
                    continue

                if dry_run:
                    logger.debug(
                        f"[DRY RUN] would upsert: {listing['external_id']} "
                        f"builder_id={builder_id} matched_alias={alias_name!r}"
                    )
                else:
                    is_new = upsert_listing(conn, builder_id, alias_name, run_id, listing)
                    if is_new:
                        listings_new += 1

        except Exception as exc:
            logger.error(f"Error scraping alias {alias_name!r}: {exc}", exc_info=True)
            error_msg = str(exc)
            overall_status = "partial"

        aliases_processed += 1
        total_listings_found += listings_found
        total_listings_new   += listings_new
        processed_builder_ids.add(builder_id)

        logger.info(
            f"{alias_name!r}: found={listings_found} new={listings_new}"
            + (f" error={error_msg}" if error_msg else "")
        )

    if not dry_run:
        finish_run(
            conn, run_id, overall_status,
            aliases_processed, total_listings_found, total_listings_new,
        )
        update_builders_last_scraped(conn, processed_builder_ids)

    if conn is not None:
        conn.close()

    logger.info(
        f"Run complete. aliases={aliases_processed} "
        f"found={total_listings_found} new={total_listings_new} "
        f"status={overall_status}"
    )
    return {
        "run_id":            run_id,
        "status":            overall_status,
        "aliases_processed": aliases_processed,
        "listings_found":    total_listings_found,
        "listings_new":      total_listings_new,
    }


def main():
    parser = argparse.ArgumentParser(description="NSW Court Listing Scraper")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch data but don't write to database")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    configure_logging(args.debug)

    result = run(dry_run=args.dry_run)
    sys.exit(0 if result["status"] in ("success", "partial") else 1)


if __name__ == "__main__":
    main()
