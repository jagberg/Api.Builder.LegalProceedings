-- =============================================================
-- Court Scraper Schema — PostgreSQL
-- Run against an existing database:
--   psql -U scraper_user -d court_scraper -f schema.sql
--
-- Create the DB and user first (as superuser):
--   CREATE USER scraper_user WITH PASSWORD 'CHANGE_ME';
--   CREATE DATABASE court_scraper OWNER scraper_user;
-- =============================================================

-- -----------------------------------------------------------
-- builders: one row per real-world builder entity
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS builders (
    id                   SERIAL       PRIMARY KEY,
    builder_name         VARCHAR(255) NOT NULL,
    is_active            SMALLINT     NOT NULL DEFAULT 1,
    scrape_interval_days INT          NOT NULL DEFAULT 1,
    last_scraped_at      TIMESTAMP,
    created_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (builder_name)
);

-- -----------------------------------------------------------
-- builder_aliases: every search term sent to the API,
-- including the builder_name itself (inserted as first alias)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS builder_aliases (
    id          SERIAL       PRIMARY KEY,
    builder_id  INTEGER      NOT NULL REFERENCES builders(id),
    alias_name  VARCHAR(255) NOT NULL,
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (alias_name)
);

-- -----------------------------------------------------------
-- scrape_runs: one row per full execution of the scraper
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_runs (
    id                SERIAL      PRIMARY KEY,
    started_at        TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at       TIMESTAMP,
    status            VARCHAR(16) NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','success','partial','failed')),
    aliases_processed INTEGER     DEFAULT 0,
    listings_found    INTEGER     DEFAULT 0,
    listings_new      INTEGER     DEFAULT 0,
    error_message     TEXT
);

-- -----------------------------------------------------------
-- Trigger function: keep updated_at current on every UPDATE
-- -----------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------
-- court_listings: the actual scraped results
-- external_id is the unique identifier from the NSW registry
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS court_listings (
    id                SERIAL       PRIMARY KEY,
    external_id       VARCHAR(128) NOT NULL,
    builder_id        INTEGER      NOT NULL REFERENCES builders(id),
    matched_alias     VARCHAR(255) NOT NULL,

    -- Core listing fields (mapped from NSW registry API response)
    case_number       VARCHAR(64),
    parties           TEXT,
    listing_date      DATE,
    listing_time      TIME,
    court             VARCHAR(255),
    location          VARCHAR(255),
    courtroom         VARCHAR(64),
    jurisdiction      VARCHAR(128),
    listing_type      VARCHAR(128),
    presiding_officer VARCHAR(255),

    -- Housekeeping
    raw_json          JSONB,
    first_seen_run    INTEGER      NOT NULL REFERENCES scrape_runs(id),
    last_seen_run     INTEGER      NOT NULL REFERENCES scrape_runs(id),
    is_active         SMALLINT     NOT NULL DEFAULT 1,
    created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (external_id)
);

CREATE INDEX IF NOT EXISTS idx_listing_date ON court_listings (listing_date);
CREATE INDEX IF NOT EXISTS idx_builder      ON court_listings (builder_id);
CREATE INDEX IF NOT EXISTS idx_court        ON court_listings (court);
CREATE INDEX IF NOT EXISTS idx_case_number  ON court_listings (case_number);

DROP TRIGGER IF EXISTS trg_court_listings_updated_at ON court_listings;
CREATE TRIGGER trg_court_listings_updated_at
    BEFORE UPDATE ON court_listings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------
-- similar_matches: listings returned by the API that did not
-- exactly match the searched alias (fuzzy upstream matches).
-- Kept for human review — flip `reviewed` when inspected.
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS similar_matches (
    id              SERIAL       PRIMARY KEY,
    builder_id      INTEGER      NOT NULL REFERENCES builders(id),
    searched_alias  VARCHAR(255) NOT NULL,
    external_id     VARCHAR(128) NOT NULL,
    case_number     VARCHAR(64),
    parties         TEXT,
    listing_date    DATE,
    raw_json        JSONB,
    reviewed        BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (external_id, searched_alias)
);

CREATE INDEX IF NOT EXISTS idx_similar_builder  ON similar_matches (builder_id);
CREATE INDEX IF NOT EXISTS idx_similar_reviewed ON similar_matches (reviewed);

-- -----------------------------------------------------------
-- Seed: Vogue Homes builder with two aliases
-- -----------------------------------------------------------
INSERT INTO builders (builder_name) VALUES ('Vogue Homes')
    ON CONFLICT (builder_name) DO NOTHING;

INSERT INTO builder_aliases (builder_id, alias_name)
    SELECT id, 'Vogue Homes' FROM builders WHERE builder_name = 'Vogue Homes'
    ON CONFLICT (alias_name) DO NOTHING;

INSERT INTO builder_aliases (builder_id, alias_name)
    SELECT id, 'Capitol Constructions' FROM builders WHERE builder_name = 'Vogue Homes'
    ON CONFLICT (alias_name) DO NOTHING;
