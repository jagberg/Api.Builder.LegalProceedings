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
PUBLIC_API_URL=https://api.bilder.com.au
```

---

## Base URL

```
http://localhost:5001             # local dev
https://api.bilder.com.au         # production (HTTPS via nginx + Let's Encrypt)
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
  id: number | null;               // null for ephemeral results (no builder created)
  searchedAlias: string | null;    // the alias that was searched; null for ephemeral
  externalId: string;
  caseNumber: string;
  parties: string;                 // party names — inspect to decide if it's a real match
  listingDate: string | null;
  createdAt: string | null;
}

interface HearingsResponse {
  builderName: string | null;      // null when ephemeral (no builder was created)
  searchedFor: string;             // what was passed in the URL
  resolvedAlias: boolean;          // true when searchedFor !== builderName
  ephemeral: boolean;              // true when nothing was persisted (see scenarios)
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

**Response 400** (non-integer limit/offset)
```json
{ "error": "limit and offset must be integers" }
```

**Search behaviour — three scenarios**

1. **Builder already exists** (name matches a registered builder or alias): a fresh scrape runs for that builder, then DB data is returned. `hearings` has confirmed matches, `similarMatches` has unreviewed fuzzy ones. `ephemeral: false`.
2. **Unknown name, at least one exact word-boundary match in upstream results**: a builder is auto-created using the **"trading as" name** as its canonical name (the search term and short name become aliases). Exact matches go to `hearings`, fuzzy to `similarMatches`. `ephemeral: false`.
3. **Unknown name, no exact match in upstream** (e.g. short/ambiguous term like "Metri"): **nothing is persisted**. Upstream results are returned in `similarMatches` as a preview with `id: null`. `ephemeral: true`, `builderName: null`.

**Notes**
- Results ordered by `listingDate ASC`, `listingTime ASC`
- `presidingOfficer` is frequently `null` — the NSW registry does not always populate it
- `listingTime` is `HH:MM:SS` (24h). The raw NSW API returns "9:15 am" — the DB normalises it
- `resolvedAlias: false` when the canonical builder name is used directly
- `similarMatches` contains only unreviewed fuzzy matches — once approved or dismissed, they disappear from the response

---

### POST /similar-matches/{id}/approve

Approve a similar match — adds an alias to a builder and marks the match as reviewed. Future scrapes will capture results for this alias automatically.

```
POST /similar-matches/3/approve
```

**Optional body** (all fields optional):
```json
{
  "customAlias": "Capital Constructions",
  "mergeIntoBuilderId": 7
}
```

| Field | Default | Effect |
|---|---|---|
| `customAlias` | Respondent name from the case parties | Override the alias name. Default is the respondent's name extracted from the `parties` field (e.g. "CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD"), not the original search term. |
| `mergeIntoBuilderId` | the match's own builder | Attach the alias to a different builder (the similar match stays on its original builder for traceability) |

The approve action also **promotes the hearing** — the similar match's `raw_json` is re-parsed and inserted into `court_listings`, so the hearing immediately appears in the `hearings` array on the next request.

**Response 200**
```json
{
  "id": 3,
  "approved": true,
  "aliasAdded": "CAPITAL CONSTRUCTION AND REFURBISHING PTY LTD",
  "builderId": 1,
  "listingCreated": true
}
```

**Response 404** — match (or target builder, if `mergeIntoBuilderId` given) not found
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

### POST /builders/{id}/merge-into/{targetId}

Merge one builder into another. All aliases, hearings, and similar matches from the source builder move to the target; the source builder is deleted.

```
POST /builders/5/merge-into/8
```

**Response 200**
```json
{
  "sourceId": 5,
  "targetId": 8,
  "targetName": "METRICON HOMES PTY LTD",
  "aliasesMoved": 2,
  "conflictsDropped": 0,
  "listingsMoved": 14,
  "similarMoved": 3
}
```

**Response 400** — `sourceId == targetId`
**Response 404** — source or target builder not found

---

## Fetch examples (Astro / TypeScript)

```ts
const API = import.meta.env.PUBLIC_API_URL ?? 'https://api.bilder.com.au';

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

// Approve a similar match — adds it as an alias. Optionally override the
// alias name or redirect to a different builder.
export async function approveSimilarMatch(
  id: number,
  opts: { customAlias?: string; mergeIntoBuilderId?: number } = {}
) {
  const res = await fetch(`${API}/similar-matches/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts),
  });
  return res.json();
}

// Dismiss a similar match — removes it from the list without adding an alias
export async function dismissSimilarMatch(id: number) {
  const res = await fetch(`${API}/similar-matches/${id}/dismiss`, { method: 'POST' });
  return res.json();
}

// Merge one builder into another — for when duplicates are discovered
export async function mergeBuilders(sourceId: number, targetId: number) {
  const res = await fetch(`${API}/builders/${sourceId}/merge-into/${targetId}`, {
    method: 'POST',
  });
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
