# Builder Legal Proceedings API

Scrapes the [NSW Online Registry](https://onlineregistry.lawlink.nsw.gov.au/content/court-lists)
for configured building companies and serves the results via a Flask REST API.

Multiple trading names for the same builder are grouped via an alias system —
searching by "Capitol Constructions" returns the same results as "Vogue Homes".

The scraper filters out fuzzy matches from the upstream API (e.g. "CAPITAL
CONSTRUCTION AND REFURBISHING" when searching "Capitol Constructions") and
stores them in a `similar_matches` table for review.

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

### Deploying updates (manual)

```bash
git pull
docker compose up -d --build api
```

### Continuous deployment via GitHub Actions

Every push to `main` automatically runs the unit tests then deploys to
Lightsail if they pass. To enable this, add two secrets to the GitHub repo:

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|---|---|
| `LIGHTSAIL_HOST` | Public IP of the Lightsail instance |
| `LIGHTSAIL_SSH_KEY` | Contents of the instance's `.pem` private key |

To get the private key contents:
```bash
cat ~/path/to/your-lightsail-key.pem
```
Paste the full output (including `-----BEGIN RSA PRIVATE KEY-----` lines) as the secret value.

The Lightsail instance must also be able to `git pull` from GitHub. If you
cloned via SSH (`git@github.com:...`), add a deploy key:

```bash
# On the Lightsail instance — generate a deploy key
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub
```

Add the public key output to **GitHub repo → Settings → Deploy keys** (read-only is enough). Then on the instance:
```bash
# Tell git to use it
git config core.sshCommand "ssh -i ~/.ssh/github_deploy -F /dev/null"
```

---

## Project structure

```
app.py                    Flask routes
scraper/
  client.py               NSW Registry API client + parse_listing()
  db.py                   All PostgreSQL helpers
  main.py                 run() — shared by CLI and Flask routes
  matching.py             Alias-to-parties word-boundary filter
schema.sql                DDL + seed data (auto-loaded by Docker on first run)
specs/
  api-reference.md        Endpoint docs and TypeScript types for the frontend
  court-scraper-api/      Full speckit docs (spec, plan, data model, contracts)
tests/                    Integration tests, matching unit tests, live smoke tests
.github/workflows/        Weekly live-test CI + deploy-on-push CD
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

## Reviewing similar matches

The NSW Registry API does fuzzy matching, so searching "Capitol Constructions"
may also return results for "CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD".
These near-misses are filtered out at scrape time and stored in the
`similar_matches` table for review.

Connect to the database:
```bash
docker compose exec db psql -U scraper_user -d court_scraper
```

View unreviewed matches:
```sql
SELECT id, searched_alias, parties, listing_date
FROM similar_matches
WHERE reviewed = FALSE
ORDER BY created_at DESC;
```

Mark a match as reviewed:
```sql
UPDATE similar_matches SET reviewed = TRUE WHERE id = 42;
```

If a match is actually legitimate (e.g. a spelling variant the court used),
add it as an alias so future scrapes capture it automatically:
```sql
-- Find the builder_id
SELECT id FROM builders WHERE builder_name = 'Vogue Homes';

-- Add the new alias
INSERT INTO builder_aliases (builder_id, alias_name)
VALUES (1, 'Capital Construction');
```

The next scrape for that builder will search the new alias and any matches
will land in `court_listings` as normal.

---

## Schema changes

The `postgres_data/` bind mount persists the database on the host filesystem.
PostgreSQL only runs `schema.sql` when initialising an empty data directory,
so after schema changes you need to recreate it:

```bash
docker compose down
rm -rf postgres_data    # Linux/Mac
# On Windows: rd /s /q postgres_data
docker compose up -d db
```

This resets all data. If you need to preserve data, apply the migration
manually instead:
```bash
docker compose exec db psql -U scraper_user -d court_scraper
```
Then paste the new DDL (e.g. `CREATE TABLE IF NOT EXISTS similar_matches ...`).

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
