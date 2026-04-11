# Builder Legal Proceedings API — Reference

Use this file as context when building the Astro frontend.

## Intended page behaviour

The page uses two endpoints together:

1. **`GET /builders`** — called once on load to populate the builder list. Each builder includes all its trading-name aliases, so the page can group hearings under one card per builder (e.g. "Vogue Homes" with aliases "Capitol Constructions" shown beneath).

2. **`GET /builders/{name}/hearings`** — called when a user selects or searches for a builder. Either the canonical name or any alias can be passed — the API resolves them to the same dataset. The response includes `resolved_alias: true` and the canonical `builder_name` when an alias was used, so the UI can show a note like "Showing results for Vogue Homes".

The scrape endpoints are not used by the frontend — scraping is triggered separately via cron.

## Running the API locally

The API repo is at `git@github.com:jagberg/Api.Builder.LegalProceedings.git`.

**Prerequisites:** Docker Desktop running.

```bash
# 1. Clone the API repo (separate from the Astro project)
git clone git@github.com:jagberg/Api.Builder.LegalProceedings.git
cd Api.Builder.LegalProceedings

# 2. Create the env file
cp .env.example .env
# Edit .env and set DB_PASSWORD to any value e.g. "localdev"

# 3. Start Postgres (seeds schema + Vogue Homes on first run)
docker compose up -d db

# 4. Start the Flask API
pip install -r requirements.txt
py -3 app.py          # Windows
python3 app.py        # Mac/Linux
# → Listening on http://localhost:5001
```

**Verify it's working:**
```bash
curl http://localhost:5001/builders
# Should return Vogue Homes with Capitol Constructions alias

curl "http://localhost:5001/builders/Vogue%20Homes/hearings"
# Returns empty hearings array until a scrape has run

# Seed some data by triggering a scrape:
curl -X POST http://localhost:5001/builders/Vogue%20Homes/scrape
# Then re-check /hearings — results should appear
```

**Astro env setup** — add to your Astro project's `.env`:
```
PUBLIC_API_URL=http://localhost:5001
```

---

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

## Fetch examples (Astro / TypeScript)

```ts
const API = import.meta.env.PUBLIC_API_URL ?? 'http://localhost:5001';

// Load all builders for the grouped page list
export async function getBuilders(): Promise<Builder[]> {
  const res = await fetch(`${API}/builders`);
  if (!res.ok) throw new Error(`GET /builders → ${res.status}`);
  const data = await res.json();
  return data.builders;
}

// Hearings for a selected builder — accepts canonical name or any alias
export async function getHearings(
  name: string,
  opts: { fromDate?: string; toDate?: string; limit?: number; offset?: number } = {}
): Promise<HearingsResponse | null> {
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
