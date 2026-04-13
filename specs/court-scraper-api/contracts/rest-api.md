# REST API Contract — Builder Legal Proceedings API

Base URL: `http://<host>:5001`
All responses: `Content-Type: application/json`
No authentication required (internal network only).

All JSON keys and query parameters use **camelCase**.

---

## GET /builders

List all builders with aliases and scrape configuration.

### Response 200
```json
{
  "builders": [
    {
      "id": 1,
      "builderName": "Vogue Homes",
      "isActive": true,
      "scrapeIntervalDays": 1,
      "lastScrapedAt": "2026-04-05 02:30:00",
      "aliases": ["Vogue Homes", "Capitol Constructions"]
    }
  ]
}
```

---

## GET /builders/{name}/hearings

Return court hearings for a builder. `{name}` may be the canonical `builderName` **or any alias** — both resolve to the same dataset.

URL-encode spaces: `Vogue%20Homes` or `Vogue+Homes`.

### Query Parameters
| Param | Type | Default | Description |
|---|---|---|---|
| fromDate | YYYY-MM-DD | — | Inclusive start date filter on `listingDate` |
| toDate | YYYY-MM-DD | — | Inclusive end date filter on `listingDate` |
| limit | integer | 50 | Max results returned. Hard cap: 200 |
| offset | integer | 0 | Pagination offset |

### Response 200
```json
{
  "builderName": "Vogue Homes",
  "searchedFor": "Capitol Constructions",
  "resolvedAlias": true,
  "aliases": ["Vogue Homes", "Capitol Constructions"],
  "total": 14,
  "offset": 0,
  "limit": 50,
  "hearings": [
    {
      "externalId": "20250023156931041486ContestedHearing",
      "matchedAlias": "Capitol Constructions",
      "caseNumber": "2025/00231569",
      "parties": "Oscar Downing v CAPITOL CONSTRUCTIONS PTY. LIMITED trading as VOGUE HOMES NSW",
      "listingDate": "2026-04-22",
      "listingTime": "09:15:00",
      "court": "NCAT CCD",
      "location": "NCAT Liverpool (CCD)",
      "courtroom": "Unassigned",
      "jurisdiction": "NCAT",
      "listingType": "Contested Hearing",
      "presidingOfficer": null,
      "createdAt": "2026-04-05 10:00:00",
      "updatedAt": "2026-04-05 10:00:00"
    }
  ]
}
```

**Notes:**
- `resolvedAlias: false` and `searchedFor == builderName` when the canonical name is used
- `presidingOfficer` is frequently `null` — the NSW API does not always return this field
- `listingTime` is returned in `HH:MM:SS` format (PostgreSQL TIME round-trip normalisation)
- Results ordered by `listingDate ASC`, `listingTime ASC NULLS LAST`

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

If `{name}` does not match any existing builder or alias, the builder is **automatically created** with `scrapeIntervalDays = 20` and `{name}` registered as its first alias.

### Response 200 — existing builder
```json
{
  "runId": 1,
  "status": "success",
  "aliasesProcessed": 2,
  "listingsFound": 14,
  "listingsNew": 3,
  "builderCreated": false,
  "scrapeIntervalDays": 1
}
```

### Response 201 — new builder auto-created
```json
{
  "runId": 2,
  "status": "success",
  "aliasesProcessed": 1,
  "listingsFound": 5,
  "listingsNew": 5,
  "builderCreated": true,
  "scrapeIntervalDays": 20
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

Scrape all active builders that are **due** based on their `scrapeIntervalDays`. Intended to be called by the daily cron job.

Due condition per builder:
```
last_scraped_at IS NULL
OR last_scraped_at < NOW() - (scrape_interval_days || ' days')::INTERVAL
```

A builder with `scrapeIntervalDays = 20` is skipped on days it is not due.

### Response 200
```json
{
  "runId": 3,
  "status": "success",
  "aliasesProcessed": 4,
  "listingsFound": 28,
  "listingsNew": 7
}
```

If no builders are due: `aliasesProcessed: 0`, `listingsFound: 0`, `listingsNew: 0`.

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

**Key fields in each hit (upstream snake_case — mapped by `parse_listing`):**
| Field | Maps to API response |
|---|---|
| id | externalId |
| scm_case_number | caseNumber |
| case_title | parties |
| scm_dateyear | listingDate (format: "22 Apr 2026") |
| time_listed | listingTime (format: "9:15 am") |
| scm_jurisdiction_court_short | court |
| location | location |
| court_room_name | courtroom |
| scm_jurisdiction_type | jurisdiction |
| jl_listing_type_ds | listingType |
