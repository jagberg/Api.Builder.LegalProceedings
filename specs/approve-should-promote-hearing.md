# Approve should promote the hearing immediately

## Current behaviour

`POST /similar-matches/{id}/approve`:
1. Marks the similar match as reviewed (removes from `similarMatches`)
2. Adds `searchedAlias` as an alias on the builder
3. Does NOT add the case to the builder's confirmed hearings

The hearing only appears after a future scrape — and often never, because:
- The `searchedAlias` is usually already registered (e.g. "dove")
- The similar match was a fuzzy hit (e.g. "Dave" ≈ "Dove") so the exact-match scraper won't find it

## Expected behaviour

When a similar match is approved:

1. **Promote the hearing immediately** — copy the similar match's case data (`externalId`, `caseNumber`, `parties`, `listingDate`, `listingTime`, `court`, `location`, `courtroom`, `jurisdiction`, `listingType`, `presidingOfficer`) into the builder's hearings table. The row should appear in `GET /builders/{name}/hearings` on the next call.

2. **Use the actual party name as the alias** (not `searchedAlias`) — or accept an optional `customAlias` override in the request body (this already exists in the spec but defaults to `searchedAlias` which is often unhelpful).

## Why this matters

Without this, the approve button is misleading — the user clicks "Approve", the similar match disappears, but the hearing never shows up in the confirmed table. Even a page refresh doesn't help because the scrape still searches by exact alias.

## Frontend impact

Once this is fixed, the frontend will re-fetch the hearings table after a successful approve to show the promoted hearing without a page reload.
