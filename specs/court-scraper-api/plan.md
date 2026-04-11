# Technical Plan — Builder Legal Proceedings API

## Stack
| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.12 | Type hints, clean async-ready, wide library support |
| Web framework | Flask 3.1 | Lightweight, no boilerplate for a small internal API |
| Database | PostgreSQL 16 | JSONB for raw blobs, robust upsert with `ON CONFLICT`, trigger support |
| DB driver | psycopg2-binary | Self-contained wheel, no system libs required in Docker |
| HTTP client | requests + tenacity | Simple sync HTTP with declarative retry/backoff |
| Container | Docker + Compose | Single `docker compose up -d db api` gets everything running |

---

## Architecture

```
┌─────────────────────────────────────────┐
│  Flask API (app.py)                     │
│  POST /builders/scrape                  │
│  POST /builders/<name>/scrape           │
│  GET  /builders                         │
│  GET  /builders/<name>/hearings         │
└────────────┬────────────────────────────┘
             │ imports
┌────────────▼────────────────────────────┐
│  scraper/main.py  — run()               │
│  scraper/db.py    — query helpers       │
│  scraper/client.py — NSW API client     │
└────────────┬────────────────────────────┘
             │
┌────────────▼──────────┐   ┌─────────────────────────────┐
│  PostgreSQL            │   │  NSW Registry API            │
│  (Docker, bind-mount   │   │  api.onlineregistry.         │
│  ./postgres_data)      │   │  justice.nsw.gov.au          │
└────────────────────────┘   └─────────────────────────────┘
```

---

## Key Design Decisions

### Builder / alias separation
`builders` holds one canonical entity. `builder_aliases` holds every search term. All `court_listings` point to `builder_id` (the parent), never the alias. This means any alias resolves to the full combined dataset in a single query — no UNION needed.

### Alias resolution in GET /hearings
Rather than requiring the canonical name, the endpoint resolves against both `builders.builder_name` and `builder_aliases.alias_name`:
```sql
WHERE b.is_active = 1 AND (b.builder_name = %s OR ba.alias_name = %s)
```
The response includes `resolved_alias: true` and the canonical `builder_name` so callers know what the name resolved to.

### Auto-creation with 20-day interval
Builders created implicitly via `POST /builders/<name>/scrape` get `scrape_interval_days = 20`. Daily builders are seeded manually with the default of 1. This avoids thrashing the NSW API for ad-hoc lookups.

### Scrape interval enforcement
`POST /builders/scrape` (cron) uses `fetch_active_aliases(conn, due_only=True)`. The due filter runs in SQL, not Python, so no aliases are fetched for builders that aren't due. `POST /builders/<name>/scrape` always runs regardless of interval — explicit triggers bypass the schedule.

### Upsert safety
`ON CONFLICT (external_id) DO UPDATE` makes every scrape run idempotent. `first_seen_run` and `created_at` are never overwritten. `last_seen_run` is always updated so you can tell if a listing is still appearing in current searches.

### `matched_alias` traceability
Stored on every `court_listings` row. When a case title says "trading as", `matched_alias` tells you which search term surfaced it.

### No per-alias status tracking
Stats are aggregated at `scrape_runs` level only. Per-alias errors appear in logs. Keeping `scrape_status` out of the schema reduces write amplification on every scrape.

---

## File Structure
```
.
├── scraper/
│   ├── __init__.py
│   ├── client.py       # RegistryClient, parse_listing(), _date_range()
│   ├── db.py           # get_connection, fetch_active_aliases, create_builder,
│   │                   # update_builders_last_scraped, start_run, finish_run,
│   │                   # upsert_listing
│   └── main.py         # run(dry_run, aliases) → dict
├── app.py              # Flask routes
├── schema.sql          # DDL + seed data (auto-loaded by Docker on first run)
├── docker-compose.yml  # db + api services, bind-mount ./postgres_data
├── Dockerfile          # python:3.12-slim, no system deps needed
├── requirements.txt
└── .env
```

---

## Environment
```
DB_HOST       127.0.0.1 locally; docker-compose overrides to 'db' for containers
DB_PORT       5432
DB_NAME       court_scraper
DB_USER       scraper_user
DB_PASSWORD   ...
SCRAPER_LOG_LEVEL  INFO
```

---

## Running Locally
```bash
docker compose up -d db          # starts postgres, loads schema.sql on first run
py -3 -m scraper.main --dry-run  # test scraper without writing
py -3 app.py                     # start Flask on :5001
```

## Deploying to Lightsail
```bash
cp .env.example .env             # fill in credentials
mkdir -p logs
docker compose up -d db api      # starts both services
# add cron: 30 2 * * * curl -s -X POST http://localhost:5001/builders/scrape
```

Data persists in `./postgres_data/` on the host. Backup:
```bash
docker compose exec db pg_dump -U scraper_user court_scraper > backup_$(date +%F).sql
```
