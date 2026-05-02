# Upsert Immutability

`court_listings` upserts on `external_id`. Some fields are immutable.

**Never overwritten on conflict:**
- `first_seen_run`, `created_at`

**Always refreshed on conflict:**
- `last_seen_run`, `listing_date`, `listing_time`, `court`, `location`,
  `courtroom`, `listing_type`, `presiding_officer`, `raw_json`, `is_active`

Use `(xmax = 0) AS inserted` in `RETURNING` to detect insert vs update.
