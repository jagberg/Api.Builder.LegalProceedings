# NSW Court Listing Scraper

Scrapes the [NSW Online Registry court lists](https://onlineregistry.lawlink.nsw.gov.au/content/court-lists)
for configured company names and stores results in MySQL.

Runs as a Docker container, triggered by cron on your Lightsail host.

---

## Directory structure

```
court-scraper/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── schema.sql          ← run once to set up MySQL
├── .env.example        ← copy to .env and fill in
├── cron_setup.sh       ← installs the host cron job
└── scraper/
    ├── __init__.py
    ├── main.py         ← entry point
    ├── client.py       ← NSW Registry API client
    └── db.py           ← MySQL helpers
```

---

## 1. First-time setup on Lightsail

### Create a MySQL user for the scraper

```sql
CREATE USER 'scraper_user'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT, INSERT, UPDATE ON court_scraper.* TO 'scraper_user'@'%';
FLUSH PRIVILEGES;
```

### Apply the schema

```bash
mysql -u root -p < schema.sql
```

### Add companies to scrape

```sql
USE court_scraper;
INSERT INTO companies (name, search_term) VALUES
  ('Capitol Constructions', 'Capitol constructions'),
  ('Acme Builders', 'Acme builders');   -- add more as needed
```

---

## 2. Configure environment

```bash
cp .env.example .env
nano .env   # fill in DB_PASSWORD and verify other values
```

`DB_HOST` should be `host.docker.internal` when running in Docker on Linux
(the `extra_hosts` line in docker-compose.yml handles the DNS resolution).

---

## 3. Build the Docker image

```bash
docker compose build
```

---

## 4. Test run

```bash
# Dry run — fetches from API, prints results, writes nothing to DB
docker compose run --rm scraper --dry-run --debug

# Real run
docker compose run --rm scraper
```

---

## 5. Install cron (runs at 02:30 daily)

```bash
chmod +x cron_setup.sh
./cron_setup.sh
```

To change the schedule, edit the `CRON_JOB` line in `cron_setup.sh` before running,
or edit your crontab directly with `crontab -e`.

Common schedules:
```
30 2 * * *    # 02:30 daily          (recommended)
0 */4 * * *   # every 4 hours        (for fast-changing lists)
0 1 * * 1     # 01:00 every Monday   (weekly)
```

---

## 6. ⚠️ Verify the API endpoint

The NSW Registry site is a JavaScript SPA that calls an internal REST API.
The endpoint used in `client.py` is reverse-engineered from the URL fragment.

**You must verify this before relying on the scraper:**

1. Open Chrome DevTools → Network tab → filter by `XHR` / `Fetch`
2. Navigate to the court lists search URL and run a search
3. Find the API call (look for JSON responses with listing data)
4. Update `BASE_API_URL` and the field mapping in `parse_listing()` in `client.py`

The response field names in `parse_listing()` are labelled with ⚠️ comments
— map them to the actual keys from the API response.

---

## 7. Adding more companies

```sql
INSERT INTO companies (name, search_term) VALUES ('Your Company', 'Your company');
```

To pause scraping a company without deleting it:
```sql
UPDATE companies SET is_active = 0 WHERE search_term = 'Your company';
```

---

## 8. Querying results

```sql
-- All upcoming listings
SELECT c.name, cl.listing_date, cl.listing_time, cl.court, cl.courtroom,
       cl.listing_type, cl.parties
FROM court_listings cl
JOIN companies c ON c.id = cl.company_id
WHERE cl.listing_date >= CURDATE()
  AND cl.is_active = 1
ORDER BY cl.listing_date, cl.listing_time;

-- New listings found in the last run
SELECT sr.started_at, c.name, cl.listing_date, cl.court, cl.parties
FROM court_listings cl
JOIN scrape_runs sr ON sr.id = cl.first_seen_run
JOIN companies c ON c.id = cl.company_id
WHERE cl.first_seen_run = (SELECT MAX(id) FROM scrape_runs WHERE status = 'success')
ORDER BY cl.listing_date;

-- Run history
SELECT id, started_at, finished_at, status,
       companies_processed, listings_found, listings_new
FROM scrape_runs ORDER BY id DESC LIMIT 20;
```

---

## 9. Log rotation (optional but recommended)

```bash
sudo tee /etc/logrotate.d/court_scraper <<'EOF'
/var/log/court_scraper_cron.log /path/to/court-scraper/logs/scraper.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
}
EOF
```
