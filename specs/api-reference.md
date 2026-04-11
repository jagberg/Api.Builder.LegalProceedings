# Builder Legal Proceedings API — Reference

Use this file as context when building the Astro frontend.

## Base URL

```
http://localhost:5001          # local dev
http://<lightsail-ip>:5001    # production (internal network only, no auth)
```

All responses are `Content-Type: application/json`.

---

## TypeScript types

```ts
interface Builder {
  id: number;
  builder_name: string;
  is_active: boolean;
  scrape_interval_days: number;
  last_scraped_at: string | null;  // "2026-04-05 02:30:00" or null
  aliases: string[];
}

interface Hearing {
  external_id: string;
  matched_alias: string;           // which alias matched at scrape time
  case_number: string;             // "2025/00231569"
  parties: string;                 // "John Smith v VOGUE HOMES NSW PTY LTD"
  listing_date: string;            // "2026-04-22"
  listing_time: string;            // "09:15:00"  (24h, HH:MM:SS)
  court: string;                   // "NCAT CCD"
  location: string;                // "NCAT Liverpool (CCD)"
  courtroom: string;               // "Courtroom 3" | "Unassigned"
  jurisdiction: string;            // "NCAT"
  listing_type: string;            // "Contested Hearing"
  presiding_officer: string | null;
  created_at: string;              // "2026-04-05 10:00:00"
  updated_at: string;
}

interface HearingsResponse {
  builder_name: string;       // canonical name e.g. "Vogue Homes"
  searched_for: string;       // what was passed in the URL
  resolved_alias: boolean;    // true when searched_for !== builder_name
  aliases: string[];
  total: number;
  offset: number;
  limit: number;
  hearings: Hearing[];
}
```

---

## Endpoints

### GET /builders

List every builder and their aliases.

```
GET /builders
```

**Response 200**
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

### GET /builders/{name}/hearings

Return court hearings for a builder. `{name}` can be the canonical name **or any alias** — both return the same combined dataset.

```
GET /builders/Vogue%20Homes/hearings
GET /builders/Capitol%20Constructions/hearings   ← same results
```

**Query parameters**

| Param | Type | Default | Notes |
|---|---|---|---|
| `from_date` | YYYY-MM-DD | — | Inclusive start on `listing_date` |
| `to_date` | YYYY-MM-DD | — | Inclusive end on `listing_date` |
| `limit` | integer | 50 | Hard cap: 200 |
| `offset` | integer | 0 | For pagination |

**Response 200**
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

**Response 404**
```json
{ "error": "Builder not found: Acme Constructions" }
```

**Response 400** (non-integer limit/offset)
```json
{ "error": "limit and offset must be integers" }
```

**Notes**
- Results ordered by `listing_date ASC`, `listing_time ASC`
- `presiding_officer` is frequently `null` — the NSW registry does not always populate it
- `listing_time` is `HH:MM:SS` (24h). The raw NSW API returns "9:15 am" — the DB normalises it
- `resolved_alias: false` when the canonical builder name is used directly

---

### POST /builders/{name}/scrape

Trigger a fresh scrape for one builder against the NSW registry. If the builder does not exist it is auto-created with a 20-day scrape interval.

```
POST /builders/Vogue%20Homes/scrape
```

No request body required.

**Response 200** — existing builder
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

**Response 201** — builder was auto-created
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

| `status` value | Meaning |
|---|---|
| `success` | All aliases scraped without error |
| `partial` | At least one alias errored; others succeeded |
| `failed` | Unhandled exception |

---

### POST /builders/scrape

Scrape all active builders that are **due** based on `scrape_interval_days`. Intended for the daily cron job — builders not yet due are silently skipped.

```
POST /builders/scrape
```

No request body required.

**Response 200**
```json
{
  "run_id": 3,
  "status": "success",
  "aliases_processed": 4,
  "listings_found": 28,
  "listings_new": 7
}
```

If no builders are due, all counts are `0`.

---

## Fetch examples (Astro / TypeScript)

```ts
const API = import.meta.env.PUBLIC_API_URL ?? 'http://localhost:5001';

// List all builders
export async function getBuilders(): Promise<Builder[]> {
  const res = await fetch(`${API}/builders`);
  if (!res.ok) throw new Error(`GET /builders → ${res.status}`);
  const data = await res.json();
  return data.builders;
}

// Hearings for one builder (alias-aware)
export async function getHearings(
  name: string,
  opts: { fromDate?: string; toDate?: string; limit?: number; offset?: number } = {}
): Promise<HearingsResponse> {
  const params = new URLSearchParams();
  if (opts.fromDate) params.set('from_date', opts.fromDate);
  if (opts.toDate)   params.set('to_date',   opts.toDate);
  if (opts.limit)    params.set('limit',      String(opts.limit));
  if (opts.offset)   params.set('offset',     String(opts.offset));

  const url = `${API}/builders/${encodeURIComponent(name)}/hearings?${params}`;
  const res = await fetch(url);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GET /builders/${name}/hearings → ${res.status}`);
  return res.json();
}

// Trigger scrape for one builder
export async function scrapeBuilder(name: string) {
  const res = await fetch(`${API}/builders/${encodeURIComponent(name)}/scrape`, {
    method: 'POST',
  });
  return res.json();
}
```

---

## Field formatting notes for display

| Field | Raw value | Display suggestion |
|---|---|---|
| `listing_date` | `"2026-04-22"` | `new Date("2026-04-22").toLocaleDateString('en-AU')` → "22/04/2026" |
| `listing_time` | `"09:15:00"` | Trim seconds: `"09:15:00".slice(0, 5)` → "09:15" |
| `last_scraped_at` | `"2026-04-05 02:30:00"` | `new Date("2026-04-05 02:30:00")` (UTC) |
| `presiding_officer` | `null` or string | Show "—" when null |
| `resolved_alias` | `true` | Show "Showing results for Vogue Homes" banner |
