# Spec — Builder Legal Proceedings API

## Overview
A scraper and REST API that monitors NSW court listings for building companies. It queries the NSW Online Registry, stores scheduled court hearings in PostgreSQL, and exposes the data via a Flask API. Multiple trading names for the same builder are transparently grouped under one entity using an alias system.

---

## User Stories

### Scraping

**As a scheduled job,** I want to scrape all active builders that are due for a scrape, so that the database stays current without re-scraping builders more frequently than their configured interval.

Acceptance criteria:
- `POST /builders/scrape` scrapes only builders where `last_scraped_at IS NULL` or `last_scraped_at < NOW() - scrape_interval_days`
- Each alias is searched separately against the NSW API using `nameOfParty`
- Results from all aliases are stored under the same `builder_id`
- `last_scraped_at` is updated on the builder row after all its aliases complete
- The response includes `aliases_processed`, `listings_found`, `listings_new`

**As a user,** I want to trigger a scrape for a specific builder by name, so that I can refresh data on demand without running a full scrape.

Acceptance criteria:
- `POST /builders/<name>/scrape` scrapes only that builder's aliases
- If the builder name does not exist it is automatically created with `scrape_interval_days = 20`
- Auto-created builders return HTTP 201 with `builder_created: true` in the response
- Existing builders return HTTP 200

---

### Querying

**As a consumer,** I want to retrieve all court hearings for a builder by name or alias, so that I can display upcoming matters regardless of which trading name was used.

Acceptance criteria:
- `GET /builders/<name>/hearings` accepts the canonical name **or any alias**
- "Capitol Constructions" and "Vogue Homes" return identical hearing data
- Response includes `resolved_alias: true` and the canonical `builder_name` when an alias was used
- Response includes the full `aliases` list so the consumer knows all known names
- Supports `from_date`, `to_date`, `limit`, `offset` query params
- Results ordered by `listing_date ASC`, `listing_time ASC NULLS LAST`
- Returns HTTP 404 if the name does not match any builder or alias

**As a consumer,** I want to list all builders with their aliases and scrape configuration, so that I can see what is being monitored and how often.

Acceptance criteria:
- `GET /builders` returns all builders regardless of `is_active` status
- Each builder includes `aliases`, `scrape_interval_days`, `last_scraped_at`

---

### Builder Management

**As a user,** I want unknown builder names to be automatically registered when I trigger a scrape, so that I can start monitoring a new name without a separate setup step.

Acceptance criteria:
- Auto-created builders get `scrape_interval_days = 20` (assumed low-priority)
- The builder name is registered as its first alias automatically
- Subsequent `POST /builders/<name>/scrape` calls use the existing record

---

## Non-Functional Requirements

- Re-running the scraper must never create duplicate listings (`external_id` is the upsert key)
- The scraper retries failed API calls up to 4 times with exponential backoff
- Requests to the NSW API are rate-limited to one page every 2 seconds
- The Flask API and scraper share DB logic via `scraper/db.py` — no duplication
- All DB writes are safe to re-run (idempotent)

---

## Out of Scope
- Authentication on the Flask API (assumed internal/private network)
- Webhook notifications for new listings
- Historical data beyond what the NSW API returns ("All available dates" = last 7 days through next 3 weeks)
