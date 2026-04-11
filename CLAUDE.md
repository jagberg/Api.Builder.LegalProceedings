# CLAUDE.md — Builder Legal Proceedings API

## What this is
A Python scraper + Flask REST API that monitors NSW court listings for building companies. It queries the NSW Online Registry, stores hearings in PostgreSQL, and serves them via a REST API. Multiple trading names for the same builder are grouped via an alias system.

## Specs
Full specs live in `specs/court-scraper-api/`:
- `spec.md` — user stories and acceptance criteria
- `plan.md` — architecture and design decisions
- `data-model.md` — full schema with relationships
- `contracts/rest-api.md` — every endpoint, params, and response shapes

Read these before adding features.

## Stack
- Python 3.12, Flask 3.1, PostgreSQL 16, psycopg2-binary
- Docker Compose for local dev and Lightsail deployment
- `requests` + `tenacity` for NSW API calls with retry/backoff

## Structure
```
scraper/client.py   NSW registry API client + parse_listing()
scraper/db.py       All DB helpers — never write raw SQL in app.py
scraper/main.py     run(dry_run, aliases) → dict — shared by CLI and Flask
app.py              Flask routes only — business logic stays in scraper/
schema.sql          DDL + seed data, auto-loaded by Docker on first run
```

## Key conventions
- All DB logic goes in `scraper/db.py`. Routes in `app.py` call helpers, never raw psycopg2.
- `run()` in `scraper/main.py` is the single scrape entry point — reused by CLI and all Flask routes.
- Builder aliases: `builder_aliases` stores every search name. `court_listings.builder_id` always points to the parent builder, never an alias. Querying by any alias returns the full combined dataset.
- New routes follow the `/builders/<name>/...` pattern. Use `unquote(name)` on path params.
- Alias resolution SQL: `WHERE b.builder_name = %s OR ba.alias_name = %s` joined via `builder_aliases`.
- Use `psycopg2.extras.RealDictCursor` for SELECT queries that return rows as dicts.
- Serialise `DATE`/`TIME`/`TIMESTAMP` columns with `str()` before `jsonify()`.

## Running locally
```bash
docker compose up -d db    # starts postgres, seeds schema on first run
py -3 app.py               # Flask on :5001
py -3 -m scraper.main --dry-run --debug
```

## Database
- PostgreSQL in Docker, data persists in `./postgres_data/` on the host
- Connect locally: `docker compose exec db psql -U scraper_user -d court_scraper`
- Schema changes: edit `schema.sql`, then `docker compose down -v && docker compose up -d db`

## NSW Registry API
```
GET https://api.onlineregistry.justice.nsw.gov.au/courtlistsearch/listings
params: nameOfParty, startDate, endDate, offset, count
response: { "hits": [...], "total": N }
```
Field mapping is in `scraper/client.py → parse_listing()`. Confirmed live and working.

## Gotchas
- `scrape_interval_days`: seeded builders default to 1 (daily). Auto-created builders get 20.
- `POST /builders/scrape` (cron) uses `due_only=True` — skips builders not yet due.
- `POST /builders/<name>/scrape` always runs regardless of interval.
- Auto-created builders return HTTP 201 with `builder_created: true`.
- Flask route order matters: `/builders/scrape` must be registered before `/builders/<name>/scrape`.
