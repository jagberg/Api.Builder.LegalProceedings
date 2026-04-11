# Builder Legal Proceedings API

Scrapes the [NSW Online Registry](https://onlineregistry.lawlink.nsw.gov.au/content/court-lists)
for configured building companies and serves the results via a Flask REST API.

Multiple trading names for the same builder are grouped via an alias system —
searching by "Capitol Constructions" returns the same results as "Vogue Homes".

---

## Stack

- Python 3.12, Flask 3.1, PostgreSQL 16
- Docker Compose — Postgres + API both run in containers
- Data persists in `./postgres_data/` on the host filesystem

---

## Local development

**Prerequisites:** Docker Desktop running.

```bash
cp .env.example .env
# Set DB_PASSWORD to any value e.g. "localdev"

docker compose up -d db     # starts Postgres, seeds schema on first run
python app.py               # Flask on http://localhost:5001
```

Verify:
```bash
curl http://localhost:5001/builders
curl -X POST http://localhost:5001/builders/Vogue%20Homes/scrape
curl http://localhost:5001/builders/Vogue%20Homes/hearings
```

Run the test suite (requires `docker compose up -d db`):
```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

---

## Deploying to Lightsail

### First-time setup

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu    # log out and back in after this

# Clone and configure
git clone git@github.com:jagberg/Api.Builder.LegalProceedings.git
cd Api.Builder.LegalProceedings
cp .env.example .env
nano .env    # set DB_PASSWORD to something strong
```

### Start the services

```bash
docker compose up -d db     # Postgres — seeds schema.sql on first run
docker compose up -d api    # Flask API on port 5001
```

Verify:
```bash
curl http://localhost:5001/builders
```

### Set up the daily scrape cron

```bash
crontab -e
```

Add:
```
30 2 * * * curl -s -X POST http://localhost:5001/builders/scrape >> ~/logs/court-scraper.log 2>&1
```

This calls `POST /builders/scrape` at 02:30 daily. Builders are only scraped
when their `scrape_interval_days` has elapsed since `last_scraped_at`.

### Deploying updates

```bash
git pull
docker compose up -d --build api
```

---

## Project structure

```
app.py                    Flask routes
scraper/
  client.py               NSW Registry API client + parse_listing()
  db.py                   All PostgreSQL helpers
  main.py                 run() — shared by CLI and Flask routes
schema.sql                DDL + seed data (auto-loaded by Docker on first run)
specs/
  api-reference.md        Endpoint docs and TypeScript types for the frontend
  court-scraper-api/      Full speckit docs (spec, plan, data model, contracts)
tests/                    74 integration tests + 5 live smoke tests
.github/workflows/        Weekly live-test CI (runs every Monday)
```

---

## Adding a builder

Via the API (auto-creates with 20-day scrape interval):
```bash
curl -X POST http://localhost:5001/builders/Metricon%20Homes/scrape
```

To add aliases for an existing builder, connect to the database directly:
```bash
docker compose exec db psql -U scraper_user -d court_scraper
```
```sql
INSERT INTO builder_aliases (builder_id, alias_name)
VALUES (1, 'Metricon');
```

---

## API endpoints

See [`specs/api-reference.md`](specs/api-reference.md) for full endpoint docs,
TypeScript types, and Astro fetch examples.

| Method | Path | Description |
|---|---|---|
| GET | `/builders` | List all builders with aliases |
| GET | `/builders/{name}/hearings` | Hearings for one builder (alias-aware) |
| POST | `/builders/{name}/scrape` | Scrape one builder now |
| POST | `/builders/scrape` | Scrape all due builders (cron target) |
