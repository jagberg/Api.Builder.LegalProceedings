# Scrape Intervals

Two values only:

| interval | who | why |
|---|---|---|
| `1` | Seeded builders (known active companies) | Daily scraping |
| `20` | Auto-created builders | Avoids thrashing NSW API for ad-hoc lookups |

- Seeded builders: set in `schema.sql` (DB default = 1)
- Auto-created builders: `create_builder(conn, name, scrape_interval_days=20)`
- `POST /builders/scrape` (cron) skips builders not yet due — filter runs in SQL
- `POST /builders/<name>/scrape` always runs regardless of interval
