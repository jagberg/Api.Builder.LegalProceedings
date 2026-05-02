# Test Structure

Tests split by dependency:

| file | type | requires |
|---|---|---|
| `test_client.py`, `test_matching.py`, `test_parties.py` | unit | nothing |
| `test_db.py`, `test_api.py` | integration | Postgres (`docker compose up -d db`) |
| `test_live.py` | live smoke | real NSW API |

## DB tests

- `clean_db` fixture truncates all tables + `RESTART IDENTITY CASCADE` before each test
- Single session-scoped `db_conn`; `clean_db` calls `rollback()` first to clear aborted txns
- NSW API mocked at `requests.Session.get` — full `RegistryClient` stack runs, only HTTP blocked
- Set `app.config["TESTING"] = True` to skip the auto-scrape in `GET /hearings`

## Mock data

`MOCK_HIT` / `MOCK_NSW_RESPONSE` in `conftest.py` mirror the confirmed live NSW payload shape.
Update these when the upstream API response schema changes.
