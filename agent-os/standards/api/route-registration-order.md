# Route Registration Order

Register literal path segments before wildcard segments.

`/builders/scrape` must be defined before `/builders/<name>/scrape`.
Flask matches top-down — without this, `POST /builders/scrape` is captured
by the `<name>` route and treated as a builder named "scrape".

- `/builders/scrape` — cron target, scrapes all due builders
- `/builders/<name>/scrape` — scrapes one specific builder

Any future literal+wildcard pairs under `/builders/` follow the same rule.
