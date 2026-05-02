# Tech Stack

## Backend

- **Python 3.12** — application language
- **Flask 3.1** — REST API framework
- **psycopg2-binary** — PostgreSQL driver
- **requests + tenacity** — NSW Registry API client with retry/backoff

## Database

- **PostgreSQL 16** — primary data store (Docker, bind-mounted to `./postgres_data/`)

## Infrastructure

- **Docker Compose** — local dev and production service orchestration
- **AWS Lightsail** — production hosting (Ubuntu 24.04, Sydney region)
- **nginx** — reverse proxy, TLS termination (Let's Encrypt)
- **GitHub Actions** — CI (unit tests) + CD (SSH deploy on push to main)

## Frontend

- **Astro** — frontend consumer of this API (separate repo)

## External APIs

- **NSW Online Registry** — `api.onlineregistry.justice.nsw.gov.au` — source of all court listing data
