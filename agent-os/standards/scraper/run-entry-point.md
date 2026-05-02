# Scrape Entry Point

`scraper.main.run()` is the single entry point for all scrape operations.

```python
from scraper.main import run

result = run(aliases=aliases_list)   # specific aliases
result = run()                        # all active aliases
```

- CLI, all Flask POST routes, and cron all call `run()` — never duplicate scrape logic
- Pass `aliases=` to scope a run to one builder; omit to scrape all due builders
- Returns `{ run_id, status, aliases_processed, listings_found, listings_new }`

**Exception:** `GET /builders/<name>/hearings` calls `RegistryClient` directly via
`_live_search()` for the live search path (when the builder doesn't exist yet in DB).
This is intentional — it's a read-only preview, not a tracked scrape run.
