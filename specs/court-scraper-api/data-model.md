# Data Model — Builder Legal Proceedings API

## Domain Entities

### Builder
A real-world building company. One row per distinct legal entity, regardless of how many trading names it uses.

```
builders
├── id                    SERIAL PRIMARY KEY
├── builder_name          VARCHAR(255) UNIQUE   — canonical/primary name
├── is_active             SMALLINT DEFAULT 1
├── scrape_interval_days  INT DEFAULT 1         — 1 = daily, 20 = every 20 days
├── last_scraped_at       TIMESTAMP             — updated after each scrape
└── created_at            TIMESTAMP
```

### Builder Alias
Every name variation sent to the NSW registry API. The canonical `builder_name` is always inserted as the first alias when a builder is created. A name can only belong to one builder (UNIQUE constraint).

```
builder_aliases
├── id           SERIAL PRIMARY KEY
├── builder_id   INT FK → builders.id
├── alias_name   VARCHAR(255) UNIQUE   — sent as nameOfParty to the NSW API
└── created_at   TIMESTAMP
```

**Example:**
```
builders:         id=1, builder_name="Vogue Homes"
builder_aliases:  id=1, builder_id=1, alias_name="Vogue Homes"
                  id=2, builder_id=1, alias_name="Capitol Constructions"
```

Both aliases are searched independently. All results land on `builder_id = 1`.

---

### Scrape Run
One row per execution of the scraper (full or partial). Tracks aggregate stats across all aliases processed in that run.

```
scrape_runs
├── id                 SERIAL PRIMARY KEY
├── started_at         TIMESTAMP DEFAULT NOW()
├── finished_at        TIMESTAMP
├── status             VARCHAR(16) CHECK IN ('running','success','partial','failed')
├── aliases_processed  INT DEFAULT 0
├── listings_found     INT DEFAULT 0
├── listings_new       INT DEFAULT 0
└── error_message      TEXT
```

`partial` = at least one alias errored but others succeeded.

---

### Court Listing
A single court hearing record from the NSW registry. Linked to the parent builder (not the alias) so all hearings for a builder are always queryable together.

```
court_listings
├── id                 SERIAL PRIMARY KEY
├── external_id        VARCHAR(128) UNIQUE   — NSW registry ID, upsert key
├── builder_id         INT FK → builders.id  — parent builder, never the alias
├── matched_alias      VARCHAR(255)          — alias used in the search (traceability)
├── case_number        VARCHAR(64)
├── parties            TEXT                  — full party string, may contain "trading as"
├── listing_date       DATE
├── listing_time       TIME
├── court              VARCHAR(255)
├── location           VARCHAR(255)
├── courtroom          VARCHAR(64)
├── jurisdiction       VARCHAR(128)
├── listing_type       VARCHAR(128)          — e.g. "Contested Hearing"
├── presiding_officer  VARCHAR(255)          — often null in practice
├── raw_json           JSONB                 — full API response blob
├── first_seen_run     INT FK → scrape_runs.id
├── last_seen_run      INT FK → scrape_runs.id
├── is_active          SMALLINT DEFAULT 1
├── created_at         TIMESTAMP
└── updated_at         TIMESTAMP             — auto-updated via trigger
```

---

### Similar Match
Listings returned by the upstream API that did not exactly match the searched alias (fuzzy upstream matches). Kept for human review — flip `reviewed` to `TRUE` when inspected. If the match is legitimate, add an alias to `builder_aliases` and re-scrape.

```
similar_matches
├── id              SERIAL PRIMARY KEY
├── builder_id      INT FK → builders.id
├── searched_alias  VARCHAR(255)          — the alias that was searched
├── external_id     VARCHAR(128)          — NSW registry ID
├── case_number     VARCHAR(64)
├── parties         TEXT
├── listing_date    DATE
├── raw_json        JSONB
├── reviewed        BOOLEAN DEFAULT FALSE — user-managed review flag
├── created_at      TIMESTAMP
└── UNIQUE (external_id, searched_alias)
```

---

## Key Relationships

```
builders 1──* builder_aliases
builders 1──* court_listings    (via builder_id)
builders 1──* similar_matches   (via builder_id)
scrape_runs 1──* court_listings (via first_seen_run, last_seen_run)
```

## Upsert Behaviour
`court_listings` uses `ON CONFLICT (external_id) DO UPDATE` — re-running the scraper is always safe. On conflict, mutable fields are refreshed (`listing_date`, `listing_time`, `court`, `location`, `courtroom`, `listing_type`, `presiding_officer`, `raw_json`, `last_seen_run`, `is_active`). `first_seen_run` and `created_at` are never overwritten.

## Indexes
```sql
idx_listing_date  ON court_listings (listing_date)
idx_builder       ON court_listings (builder_id)
idx_court         ON court_listings (court)
idx_case_number   ON court_listings (case_number)
```

## Seed Data
```sql
INSERT INTO builders (builder_name) VALUES ('Vogue Homes');
INSERT INTO builder_aliases (builder_id, alias_name) SELECT id, 'Vogue Homes' FROM builders WHERE builder_name = 'Vogue Homes';
INSERT INTO builder_aliases (builder_id, alias_name) SELECT id, 'Capitol Constructions' FROM builders WHERE builder_name = 'Vogue Homes';
```
