# Builder Legal Proceedings API

A Python scraper and Flask REST API that monitors NSW court listings for building companies. It queries the [NSW Online Registry](https://onlineregistry.lawlink.nsw.gov.au/content/court-lists), stores hearings in PostgreSQL, and serves them via a REST API consumed by an Astro frontend.

## What it does

- **Searches the NSW Registry** for building companies by name or alias
- **Filters results intelligently** — only matches where the search term appears as a word on the respondent side of the case, with a company indicator check for single-word searches (avoids matching personal surnames)
- **Extracts trading-as names** — "Metricon Homes trading as METRICON HOMES PTY LTD" auto-creates the builder with the legal name as canonical and short names as aliases
- **Groups trading names** — "Capitol Constructions" and "Vogue Homes" are aliases of the same builder; searching either returns the same combined dataset
- **Surfaces fuzzy matches for review** — upstream API results that don't match exactly go to `similarMatches` for the user to approve or dismiss
- **Auto-creates builders on first search** — searching an unknown name hits the live NSW API and returns results immediately

## Stack

- **Python 3.12**, Flask 3.1, PostgreSQL 16, psycopg2-binary
- **Docker Compose** — Postgres + API both run in containers
- **AWS Lightsail** — production deployment (Ubuntu 24.04, Sydney region)
- **GitHub Actions** — CI (unit tests on push) + CD (SSH deploy to Lightsail)
- Data persists in `./postgres_data/` on the host filesystem (bind mount)

---

## Local development

**Prerequisites:** Docker Desktop running, Python 3.12+.

```bash
# Clone and configure
git clone git@github.com:jagberg/Api.Builder.LegalProceedings.git
cd Api.Builder.LegalProceedings
cp .env.example .env
# Edit .env — set DB_PASSWORD to any value e.g. "localdev"

# Start Postgres (seeds schema + Vogue Homes builder on first run)
docker compose up -d db

# Option A: Run API via Docker
docker compose up -d --build api
# → http://localhost:5001

# Option B: Run API directly (for faster iteration)
pip install -r requirements.txt
python app.py
# → http://localhost:5001
```

**Verify:**
```bash
curl http://localhost:5001/builders
curl http://localhost:5001/builders/Vogue%20Homes/hearings
```

**Run the test suite** (requires Postgres running):
```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                              # all 140 tests
pytest tests/test_client.py tests/test_matching.py tests/test_parties.py  # unit tests only (no DB)
```

**Rebuild after code changes** (if using Docker for the API):
```bash
docker compose up -d --build api
```

---

## Production deployment (Lightsail)

### Infrastructure

| Resource | Details |
|---|---|
| **Lightsail instance** | `api-builder-legalproceedings`, Ubuntu 24.04, Sydney (ap-southeast-2) |
| **Static IP** | `52.63.163.160` attached to the instance |
| **Firewall rules** | SSH (22), HTTP (80), Custom TCP (5001) — all open to any IPv4 |
| **Docker services** | `db` (Postgres 16) + `api` (Flask on port 5001) |

### First-time instance setup

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
# Log out and back in

# Set up deploy key (so the instance can git pull from GitHub)
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub
# → Add this public key to GitHub: repo Settings → Deploy keys → Add deploy key
#   Title: "Lightsail", read-only access is enough

# Clone the repo
git clone git@github.com:jagberg/Api.Builder.LegalProceedings.git
cd ~/Api.Builder.LegalProceedings
git config core.sshCommand "ssh -i ~/.ssh/github_deploy -o IdentitiesOnly=yes"

# Configure env
cp .env.example .env
nano .env   # Set DB_PASSWORD to something strong

# Start services
docker compose up -d db     # Seeds schema.sql on first run
docker compose up -d api    # Flask API on port 5001

# Set up the scheduled scrape cron
mkdir -p ~/logs
crontab -e
# Add:
# * * * * * curl -s -X POST 'http://localhost:5001/builders/scrape?batchSize=5' >> ~/logs/court-scraper.log 2>&1
```

### Keys and secrets setup

Three sets of keys are involved:

| Key | Where it lives | What it does | How to get it |
|---|---|---|---|
| **Lightsail SSH key** (.pem) | GitHub secret `LIGHTSAIL_SSH_KEY` | GitHub Actions SSHes into Lightsail to deploy | Download from [lightsail.aws.amazon.com/ls/webapp/account/keys](https://lightsail.aws.amazon.com/ls/webapp/account/keys) for ap-southeast-2 |
| **Lightsail static IP** | GitHub secret `LIGHTSAIL_HOST` | Target IP for SSH deploy | Copy from the Lightsail instance Networking tab |
| **GitHub deploy key** (ed25519) | Generated on Lightsail, public key added to GitHub repo | Lightsail instance pulls code from GitHub | Generated via `ssh-keygen` on the instance (see setup above) |

**GitHub repository secrets** — set at [github.com/jagberg/Api.Builder.LegalProceedings/settings/secrets/actions](https://github.com/jagberg/Api.Builder.LegalProceedings/settings/secrets/actions):

| Secret | Value |
|---|---|
| `LIGHTSAIL_HOST` | `52.63.163.160` (the static IP) |
| `LIGHTSAIL_SSH_KEY` | Full contents of the `.pem` file including `-----BEGIN/END RSA PRIVATE KEY-----` lines |

**GitHub deploy key** — set at [github.com/jagberg/Api.Builder.LegalProceedings/settings/keys](https://github.com/jagberg/Api.Builder.LegalProceedings/settings/keys):

| Title | Key | Write access |
|---|---|---|
| `Lightsail` | Contents of `~/.ssh/github_deploy.pub` from the instance | No (read-only) |

### Continuous deployment

Every push to `main`:
1. **Unit tests** run in GitHub Actions (test_client, test_matching, test_parties — no DB needed)
2. If tests pass, **SSH deploy** to Lightsail: `git pull` + `docker compose up -d --build api`

The deploy can also be triggered manually from the [Actions tab](https://github.com/jagberg/Api.Builder.LegalProceedings/actions) (workflow_dispatch).

### Manual deployment

SSH into the instance and run:
```bash
cd ~/Api.Builder.LegalProceedings
git pull origin main
docker compose up -d --build api
```

### After instance reboot

Docker containers don't auto-start after a Lightsail reboot. SSH in and run:
```bash
cd ~/Api.Builder.LegalProceedings
docker compose up -d db
docker compose up -d api
```

---

## Project structure

```
app.py                    Flask routes + search logic (3 scenarios)
scraper/
  client.py               NSW Registry API client + parse_listing()
  db.py                   All PostgreSQL helpers
  main.py                 run() — scrape orchestration, shared by CLI and Flask
  matching.py             Alias-to-parties filter (respondent-only, company indicator)
  parties.py              Trading-as name extraction from case titles
schema.sql                DDL + seed data (auto-loaded by Docker on first run)
specs/
  api-reference.md        Endpoint docs, TypeScript types, fetch helpers for frontend
  court-scraper-api/      Full speckit docs (spec, plan, data model, contracts)
tests/
  test_client.py          Unit tests for NSW API client + parse_listing
  test_matching.py        Unit tests for alias matching logic
  test_parties.py         Unit tests for trading-as extraction
  test_db.py              Integration tests for DB helpers (requires Postgres)
  test_api.py             Integration tests for Flask routes (requires Postgres)
  test_live.py            Live smoke tests against the real NSW API
  conftest.py             Shared fixtures, mock data
.github/workflows/
  deploy.yml              CI/CD — unit tests + SSH deploy on push to main
  live-tests.yml          Weekly live API smoke tests (Monday 01:00 UTC)
```

---

## API endpoints

See [`specs/api-reference.md`](specs/api-reference.md) for full endpoint docs, TypeScript types, response examples, and Astro fetch helpers.

| Method | Path | Description |
|---|---|---|
| GET | `/builders` | List all builders with aliases |
| GET | `/builders/{name}/hearings` | Search/view hearings — auto-creates builders, scrapes live |
| POST | `/builders/{name}/scrape` | Trigger a scrape for one builder |
| POST | `/builders/scrape?batchSize=5` | Scrape due builders in batches (cron target) |
| POST | `/similar-matches/{id}/approve` | Approve a fuzzy match — adds alias + promotes to hearing |
| POST | `/similar-matches/{id}/dismiss` | Dismiss a fuzzy match |
| POST | `/builders/{id}/merge-into/{targetId}` | Merge duplicate builders |

---

## How search works

When `GET /builders/{name}/hearings` is called:

1. **Known builder/alias** — runs a fresh scrape, then returns confirmed hearings + unreviewed similar matches from the database
2. **Unknown name + exact match found in upstream** — auto-creates builder using the "trading as" legal name, stores exact matches as hearings and fuzzy ones as similar matches
3. **Unknown name + no exact match** — returns upstream results as ephemeral `similarMatches` (not persisted, `id: null`). No builder created.

Matching rules:
- Only the **respondent side** of the case (after "v") is checked
- **Single-word searches** (e.g. "Dove") also require a company indicator (Pty, Ltd, Homes, Constructions, etc.) — prevents matching personal surnames
- **Multi-word searches** (e.g. "Vogue Homes") use word-boundary matching directly

---

## Managing builders and aliases

**Search for a new builder** (auto-creates if matches found):
```bash
curl http://localhost:5001/builders/Metricon%20Homes/hearings
```

**Trigger a manual scrape:**
```bash
curl -X POST http://localhost:5001/builders/Metricon%20Homes/scrape
```

**Approve a similar match from the UI or API:**
```bash
curl -X POST http://localhost:5001/similar-matches/3/approve
# Optionally with a custom alias:
curl -X POST http://localhost:5001/similar-matches/3/approve \
  -H 'Content-Type: application/json' \
  -d '{"customAlias": "Capital Constructions"}'
```

**Merge duplicate builders:**
```bash
curl -X POST http://localhost:5001/builders/5/merge-into/8
```

**Add aliases via the database:**
```bash
docker compose exec db psql -U scraper_user -d court_scraper
```
```sql
INSERT INTO builder_aliases (builder_id, alias_name)
VALUES (1, 'Capital Construction');
```

**Review similar matches via the database:**
```sql
SELECT id, searched_alias, parties, listing_date
FROM similar_matches WHERE reviewed = FALSE
ORDER BY created_at DESC;
```

---

## Schema changes

PostgreSQL only runs `schema.sql` when initialising an empty data directory. After schema changes:

**Option A — Reset** (loses all data):
```bash
docker compose down
rm -rf postgres_data
docker compose up -d db
```

**Option B — Migrate** (preserves data):
```bash
docker compose exec db psql -U scraper_user -d court_scraper
-- Paste the new DDL here
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `127.0.0.1` | Postgres host. Overridden to `db` inside Docker. |
| `DB_PORT` | `5432` | Postgres port |
| `DB_NAME` | `court_scraper` | Database name |
| `DB_USER` | `scraper_user` | Database user |
| `DB_PASSWORD` | — | **Required.** Set in `.env`. |
| `SCRAPER_LOG_LEVEL` | `INFO` | Python logging level |
