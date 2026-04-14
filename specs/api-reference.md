# Builder Legal Proceedings API — Reference

Use this file as context when building the Astro frontend.

## Intended page behaviour

The page uses two endpoints together:

1. **`GET /builders`** — called once on load to populate the builder list. Each builder includes all its trading-name aliases, so the page can group hearings under one card per builder (e.g. "Vogue Homes" with aliases "Capitol Constructions" shown beneath).

2. **`GET /builders/{name}/hearings`** — called when a user selects or searches for a builder. Either the canonical name or any alias can be passed — the API resolves them to the same dataset. The response includes `resolvedAlias: true` and the canonical `builderName` when an alias was used, so the UI can show a note like "Showing results for Vogue Homes".

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
PUBLIC_API_URL=http://52.63.163.160:5001
```

---

## Base URL

```
http://localhost:5001          # local dev
http://52.63.163.160:5001     # production
```

All responses are `Content-Type: application/json`. All JSON keys and query parameters use camelCase.

---

## TypeScript types

```ts
interface Builder {
  id: number;
  builderName: string;
  isActive: boolean;
  scrapeIntervalDays: number;
  lastScrapedAt: string | null;   // "2026-04-05 02:30:00" or null
  aliases: string[];
}

interface Hearing {
  externalId: string;
  matchedAlias: string;           // which alias matched at scrape time
  caseNumber: string;             // "2025/00231569"
  parties: string;                // "John Smith v VOGUE HOMES NSW PTY LTD"
  listingDate: string;            // "2026-04-22"
  listingTime: string;            // "09:15:00"  (24h, HH:MM:SS)
  court: string;                  // "NCAT CCD"
  location: string;               // "NCAT Liverpool (CCD)"
  courtroom: string;              // "Courtroom 3" | "Unassigned"
  jurisdiction: string;           // "NCAT"
  listingType: string;            // "Contested Hearing"
  presidingOfficer: string | null;
  createdAt: string;              // "2026-04-05 10:00:00"
  updatedAt: string;
}

interface SimilarMatch {
  id: number;                      // use this ID for approve/dismiss actions
  searchedAlias: string;           // the alias that was searched
  externalId: string;
  caseNumber: string;
  parties: string;                 // party names — inspect to decide if it's a real match
  listingDate: string | null;
  createdAt: string | null;
}

interface HearingsResponse {
  builderName: string;       // canonical name e.g. "Vogue Homes"
  searchedFor: string;       // what was passed in the URL
  resolvedAlias: boolean;    // true when searchedFor !== builderName
  aliases: string[];
  total: number;
  offset: number;
  limit: number;
  hearings: Hearing[];
  similarMatches: SimilarMatch[];  // unreviewed fuzzy matches pending review
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

### GET /builders/{name}/hearings

Return court hearings for a builder. `{name}` can be the canonical name **or any alias** — both return the same combined dataset.

```
GET /builders/Vogue%20Homes/hearings
GET /builders/Capitol%20Constructions/hearings   ← same results
```

**Query parameters**

| Param | Type | Default | Notes |
|---|---|---|---|
| `fromDate` | YYYY-MM-DD | — | Inclusive start on `listingDate` |
| `toDate` | YYYY-MM-DD | — | Inclusive end on `listingDate` |
| `limit` | integer | 50 | Hard cap: 200 |
| `offset` | integer | 0 | For pagination |

**Response 200**
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
  ],
  "similarMatches": [
    {
      "id": 3,
      "searchedAlias": "Capitol Constructions",
      "externalId": "test002FuzzyMatch",
      "caseNumber": "2025/00200002",
      "parties": "Erica Lilith Mann v CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD",
      "listingDate": "2026-04-25",
      "createdAt": "2026-04-14 10:14:44"
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
- Results ordered by `listingDate ASC`, `listingTime ASC`
- `presidingOfficer` is frequently `null` — the NSW registry does not always populate it
- `listingTime` is `HH:MM:SS` (24h). The raw NSW API returns "9:15 am" — the DB normalises it
- `resolvedAlias: false` when the canonical builder name is used directly
- `similarMatches` contains only unreviewed fuzzy matches — once approved or dismissed, they disappear from the response

---

### POST /similar-matches/{id}/approve

Approve a similar match — adds the `searchedAlias` as a new builder alias and marks the match as reviewed. Future scrapes will capture results for this alias automatically.

```
POST /similar-matches/3/approve
```

**Response 200**
```json
{ "id": 3, "approved": true, "aliasAdded": "Capitol Constructions" }
```

**Response 404** — match not found
**Response 409** — already reviewed

---

### POST /similar-matches/{id}/dismiss

Mark a similar match as reviewed without adding an alias. Removes it from future `similarMatches` responses.

```
POST /similar-matches/3/dismiss
```

**Response 200**
```json
{ "id": 3, "dismissed": true }
```

**Response 404** — match not found or already reviewed

---

## Fetch examples (Astro / TypeScript)

```ts
const API = import.meta.env.PUBLIC_API_URL ?? 'http://52.63.163.160:5001';

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
  if (opts.fromDate) params.set('fromDate', opts.fromDate);
  if (opts.toDate)   params.set('toDate',   opts.toDate);
  if (opts.limit)    params.set('limit',    String(opts.limit));
  if (opts.offset)   params.set('offset',   String(opts.offset));

  const url = `${API}/builders/${encodeURIComponent(name)}/hearings?${params}`;
  const res = await fetch(url);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GET /builders/${name}/hearings → ${res.status}`);
  return res.json();
}

// Approve a similar match — adds it as an alias for future scrapes
export async function approveSimilarMatch(id: number) {
  const res = await fetch(`${API}/similar-matches/${id}/approve`, { method: 'POST' });
  return res.json();
}

// Dismiss a similar match — removes it from the list without adding an alias
export async function dismissSimilarMatch(id: number) {
  const res = await fetch(`${API}/similar-matches/${id}/dismiss`, { method: 'POST' });
  return res.json();
}
```

---

## Field formatting notes for display

| Field | Raw value | Display suggestion |
|---|---|---|
| `listingDate` | `"2026-04-22"` | `new Date("2026-04-22").toLocaleDateString('en-AU')` → "22/04/2026" |
| `listingTime` | `"09:15:00"` | Trim seconds: `"09:15:00".slice(0, 5)` → "09:15" |
| `lastScrapedAt` | `"2026-04-05 02:30:00"` | `new Date("2026-04-05 02:30:00")` (UTC) |
| `presidingOfficer` | `null` or string | Show "—" when null |
| `resolvedAlias` | `true` | Show "Showing results for Vogue Homes" banner |
