# REST API Contract — Builder Legal Proceedings API

Base URL: `http://<host>:5001`
All responses: `Content-Type: application/json`
No authentication required (internal network only).

---

## GET /builders

List all builders with aliases and scrape configuration.

### Response 200
```json
{
  "builders": [
    {
      "id": 1,
      "builder_name": "Vogue Homes",
      "is_active": true,
      "scrape_interval_days": 1,
      "last_scraped_at": "2026-04-05 02:30:00",
      "aliases": ["Vogue Homes", "Capitol Constructions"]
    }
  ]
}
```

---

## GET /builders/{name}/hearings

Return court hearings for a builder. `{name}` may be the canonical `builder_name` **or any alias** — both resolve to the same dataset.

URL-encode spaces: `Vogue%20Homes` or `Vogue+Homes`.

### Query Parameters
| Param | Type | Default | Description |
|---|---|---|---|
| from_date | YYYY-MM-DD | — | Inclusive start date filter on `listing_date` |
| to_date | YYYY-MM-DD | — | Inclusive end date filter on `listing_date` |
| limit | integer | 50 | Max results returned. Hard cap: 200 |
| offset | integer | 0 | Pagination offset |

### Response 200
```json
{
  "builder_name": "Vogue Homes",
  "searched_for": "Capitol Constructions",
  "resolved_alias": true,
  "aliases": ["Vogue Homes", "Capitol Constructions"],
  "total": 14,
  "offset": 0,
  "limit": 50,
  "hearings": [
    {
      "external_id": "20250023156931041486ContestedHearing",
      "matched_alias": "Capitol Constructions",
      "case_number": "2025/00231569",
      "parties": "Oscar Downing v CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW",
      "listing_date": "2026-04-22",
      "listing_time": "09:15:00",
      "court": "NCAT CCD",
      "location": "NCAT Liverpool (CCD)",
      "courtroom": "Unassigned",
      "jurisdiction": "NCAT",
      "listing_type": "Contested Hearing",
      "presiding_officer": null,
      "created_at": "2026-04-05 10:00:00",
      "updated_at": "2026-04-05 10:00:00"
    }
  ]
}
```

**Notes:**
- `resolved_alias: false` and `searched_for == builder_name` when the canonical name is used
- `presiding_officer` is frequently `null` — the NSW API does not always return this field
- `listing_time` is returned in `HH:MM:SS` format (PostgreSQL TIME round-trip normalisation)
- Results ordered by `listing_date ASC`, `listing_time ASC NULLS LAST`

### Response 404
```json
{ "error": "Builder not found: Acme Constructions" }
```

### Response 400
```json
{ "error": "limit and offset must be integers" }
```

---

## POST /builders/{name}/scrape

Trigger a scrape for one builder. Searches all aliases for that builder against the NSW registry.

If `{name}` does not match any existing builder or alias, the builder is **automatically created** with `scrape_interval_days = 20` and `{name}` registered as its first alias.

### Response 200 — existing builder
```json
{
  "run_id": 1,
  "status": "success",
  "aliases_processed": 2,
  "listings_found": 14,
  "listings_new": 3,
  "builder_created": false,
  "scrape_interval_days": 1
}
```

### Response 201 — new builder auto-created
```json
{
  "run_id": 2,
  "status": "success",
  "aliases_processed": 1,
  "listings_found": 5,
  "listings_new": 5,
  "builder_created": true,
  "scrape_interval_days": 20
}
```

### Status values
| Value | Meaning |
|---|---|
| success | All aliases scraped without error |
| partial | At least one alias errored; others succeeded |
| failed | Unhandled exception — check logs |

### Response 500
```json
{ "error": "..." }
```

---

## POST /builders/scrape

Scrape all active builders that are **due** based on their `scrape_interval_days`. Intended to be called by the daily cron job.

Due condition per builder:
```
last_scraped_at IS NULL
OR last_scraped_at < NOW() - (scrape_interval_days || ' days')::INTERVAL
```

A builder with `scrape_interval_days = 20` is skipped on days it is not due.

### Response 200
```json
{
  "run_id": 3,
  "status": "success",
  "aliases_processed": 4,
  "listings_found": 28,
  "listings_new": 7
}
```

If no builders are due: `aliases_processed: 0`, `listings_found: 0`, `listings_new: 0`.

### Cron setup
```
30 2 * * * curl -s -X POST http://localhost:5001/builders/scrape >> /home/ubuntu/court-scraper/logs/cron.log 2>&1
```

---

## NSW Registry — Upstream API

The scraper calls this API. Documented here for reference.

**Endpoint:** `GET https://api.onlineregistry.justice.nsw.gov.au/courtlistsearch/listings`

**Key params:**
| Param | Notes |
|---|---|
| nameOfParty | Used for builder/alias name searches |
| caseNumber | Used when term matches `\d{4}/\d{8}` or 12 digits |
| startDate | YYYY-MM-DD |
| endDate | YYYY-MM-DD |
| offset | Pagination |
| count | Page size (30) |

**Response shape:**
```json
{ "hits": [...], "total": 14, "offset": 0, "count": 30 }
```

**Key fields in each hit:**
| Field | Maps to |
|---|---|
| id | external_id |
| scm_case_number | case_number |
| case_title | parties |
| scm_dateyear | listing_date (format: "22 Apr 2026") |
| time_listed | listing_time (format: "9:15 am") |
| scm_jurisdiction_court_short | court |
| location | location |
| court_room_name | courtroom |
| scm_jurisdiction_type | jurisdiction |
| jl_listing_type_ds | listing_type |
