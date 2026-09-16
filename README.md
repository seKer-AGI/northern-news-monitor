# Northern News Monitor

Collects **weather and hazard news for Pakistan's northern areas** — Murree,
Galiyat, Kaghan/Naran, Swat, Chitral, Kohistan, Gilgit-Baltistan, Neelum/AJK and
the Karakoram Highway — from public sources that need no login, and writes a
**daily CSV**.

```text
Google News searches ─┐
Publisher RSS feeds ──┤
Official advisories ──┼─▶ fetch ─▶ window filter ─▶ relevance filter ─▶ dedupe ─▶ PostgreSQL ─▶ CSV
Open-Meteo forecasts ─┘                          (location AND hazard)
```

Example rows: "Karakoram Highway blocked today", "NDMA Weather Advisory – 11 Sep 2026",
"چترال سمیت خیبرپختونخوا میں بارش، ژالہ باری اور سیلابی صورتحال",
"Weather forecast alert – Skardu: heavy snowfall about 6 cm expected".

The project started as a Facebook post monitor, and that part still ships as an
optional module (Meta Graph API, Pages only). Facebook **Groups cannot** be read
through the official API — see [docs/meta-api.md](docs/meta-api.md).

---

## Contents

1. [What it collects](#1-what-it-collects)
2. [Architecture](#2-architecture)
3. [Installation](#3-installation)
4. [Daily use](#4-daily-use)
5. [Environment variables](#5-environment-variables)
6. [Database and migrations](#6-database-and-migrations)
7. [REST API](#7-rest-api)
8. [Docker](#8-docker)
9. [Scheduling](#9-scheduling)
10. [Facebook / Meta module](#10-facebook--meta-module)
11. [Tests](#11-tests)
12. [Security](#12-security)
13. [Data minimization and terms](#13-data-minimization-and-terms)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. What it collects

| `source_type` | What it is | Default sources |
|---|---|---|
| `google_news` | Google News RSS searches, region by region | 7 searches: Hazara/Galiyat/Kaghan · Swat/Chitral/Dir/Kohistan · Gilgit-Baltistan/KKH · Neelum/AJK · NDMA/PDMA/PMD · Rescue 1122 · NHA/NHMP/FWO roads |
| `rss` | Publisher feeds, English + Urdu | Dawn, Express Tribune, Geo, ARY, Jang (Urdu), Express (Urdu), Pamir Times, Chitral Times (Urdu + English), Chitral Today, Daily K2, Skardu.pk |
| `advisory_page` | Official pages with no feed, read only if `robots.txt` allows | NDMA advisories, PDMA Khyber Pakhtunkhwa, PMD press releases |
| `weather` | Open-Meteo forecast alerts (snow, rain, wind, thunderstorm) | 16 northern locations |
| `page` / `group` | Facebook, through the optional Meta module | none by default |

An item is kept only if it mentions a **northern location and a hazard**, in
English or Urdu. Official advisories are always kept. The same story from
several outlets is collapsed into one CSV row.

Full details, including sources that were checked and rejected:
[docs/northern-news.md](docs/northern-news.md).

## 2. Architecture

```text
 Task Scheduler / cron ─▶ python -m app collect
 n8n ─▶ POST /api/v1/collection/run
                    │
                    ▼
          ┌──────────────────┐      ┌────────────────────────┐
          │ CollectionService│ ───▶ │ RoutingProvider        │
          └────────┬─────────┘      │  ├ FeedProvider        │
                   │                │  ├ AdvisoryPageProvider│
 window · relevance · dedupe        │  ├ OpenMeteoProvider   │
                   ▼                │  └ Meta / Mock (FB)    │
          ┌──────────────────┐      └────────────────────────┘
          │   PostgreSQL     │ sources · posts ·
          └────────┬─────────┘ collection_runs · collection_errors
                   ▼
         CSV · JSON · REST API
```

Layers stay separate: `app/api` (HTTP), `app/services` (business logic),
`app/providers` (data access), `app/db` (persistence), `app/core` (config,
logging, security). See [docs/architecture.md](docs/architecture.md).

**Incremental collection.** Each source keeps its own watermark
(`last_collected_at`). A run fetches `(watermark − FETCH_OVERLAP_MINUTES, run start]`,
and the watermark moves only after that source's items are committed. A failed
source, or a missed day, is retried in full on the next run, so nothing is lost.
Items caught twice are removed by their stable ID.

## 3. Installation

Requirements: Python 3.12+, and PostgreSQL 14+ (or Docker).

```bash
git clone <your-repo-url> northern-news-monitor
cd northern-news-monitor
python -m venv .venv
pip install -e ".[dev]"
cp .env.example .env
```

On Windows, activate the environment with `.venv\Scripts\activate` and copy the
file with `copy .env.example .env`.

An internal API key is only needed for the REST API. Generate one and put it in
`.env` as `INTERNAL_API_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 4. Daily use

```bash
python -m app db migrate
python -m app sources seed-northern
python -m app collect
python -m app export news-csv --since-hours 24 -o exports/northern-weather-news.csv
```

CSV columns: `posted_at_pkt, source_name, source_type, locations, hazards, text, url`,
newest first, duplicates collapsed (`--no-dedupe` keeps every outlet).

Other commands: `sources list|add|update|remove|validate`, `runs list`,
`export csv|json`, `provider health`, `serve`, `db current|downgrade`.
`collect` exit codes: `0` success, `3` partial success, `1` failed.

## 5. Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://fpm:fpm@localhost:5432/northern_news_monitor` | SQLAlchemy URL |
| `NEWS_ENABLED` | `true` | News, weather and advisory sources on or off |
| `NEWS_USER_AGENT` | `northern-news-monitor/0.1 (...)` | Sent to every public site |
| `NEWS_MAX_RESPONSE_BYTES` | `5000000` | Response size cap |
| `NEWS_SUMMARY_CHARS` | `600` | Summary length kept from publisher feeds |
| `WEATHER_SNOWFALL_CM` / `WEATHER_PRECIPITATION_MM` / `WEATHER_WIND_GUST_KMH` | `2` / `25` / `60` | Forecast alert thresholds per day |
| `WEATHER_FORECAST_DAYS` | `3` | Forecast days checked |
| `FETCH_OVERLAP_MINUTES` | `10` | Overlap with the previous window |
| `INITIAL_LOOKBACK_HOURS` | `24` | Window for a source's first run |
| `COLLECTION_RUN_STALE_MINUTES` | `180` | A `running` run older than this is abandoned |
| `INTERNAL_API_KEY` | – | **Required for `/api/v1/*`**, bearer token |
| `CORS_ALLOWED_ORIGINS` | *(empty)* | Comma-separated origins |
| `CSV_ESCAPE_FORMULAS` | `true` | Prefix formula-like cells with an apostrophe |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | `json` or `text` |
| `DATA_PROVIDER` | `mock` | Facebook module: `mock` or `meta` |
| `META_ACCESS_TOKEN` / `META_API_VERSION` | – | Required when `DATA_PROVIDER=meta` |
| `META_APP_ID` / `META_APP_SECRET` | – | Optional; the secret enables `appsecret_proof` |

Missing required variables are reported by name, for example
`Missing required environment variables: META_ACCESS_TOKEN, META_API_VERSION`.

## 6. Database and migrations

```bash
docker compose up -d db
python -m app db migrate
python -m app db current
```

Tables: `sources`, `posts`, `collection_runs`, `collection_errors`. Items are
unique per `source_id + external_post_id`, and all timestamps are stored in UTC.

## 7. REST API

```bash
python -m app serve --reload
```

Interactive docs at `http://127.0.0.1:8000/docs`. Every `/api/v1/*` endpoint
needs `Authorization: Bearer <INTERNAL_API_KEY>`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness and database check (public) |
| GET | `/api/v1/provider/health` | Provider and credential check |
| GET, POST | `/api/v1/sources` | List and create sources |
| GET, PATCH, DELETE | `/api/v1/sources/{id}` | Read, update, delete a source |
| POST | `/api/v1/sources/{id}/validate` | Check the source can be read |
| POST | `/api/v1/collection/run` | Run collection now: 200 success or partial, 502 failed, 409 already running |
| GET | `/api/v1/collection/runs`, `/runs/{id}` | Run history and errors |
| GET | `/api/v1/posts`, `/posts/{id}` | Paginated items |
| GET | `/api/v1/export/news-csv` | Northern news CSV (`?since_hours=24`) |
| GET | `/api/v1/export/csv`, `/export/json` | Plain item export |

Filters: `source_id`, `source_type`, `start_date`, `end_date` (ISO 8601 or
`YYYY-MM-DD`). Errors use `{"error": {"code", "message", "details"}}`.

## 8. Docker

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec api python -m app sources seed-northern
docker compose exec api python -m app collect
```

The API container applies migrations on start and runs as a non-root user.

## 9. Scheduling

- **Windows:** `scripts\run-daily.ps1` starts the database, collects, and writes
  `exports\northern-weather-news-YYYY-MM-DD.csv` plus `-latest.csv`, logging to
  `exports\logs\`. Register it in Task Scheduler as a daily task; the machine
  must be on and the user logged in, because Docker Desktop needs a session.
- **cron:** `0 6 * * * cd /srv/northern-news-monitor && .venv/bin/python -m app collect`
- **n8n:** Schedule Trigger → HTTP Request `POST /api/v1/collection/run` with a
  Header Auth credential. See [docs/n8n.md](docs/n8n.md).

A missed run is not a problem: the next run collects the whole missed window.

## 10. Facebook / Meta module

Facebook **Pages** are still supported through the official Meta Graph API. A
Page you manage needs `pages_read_engagement` and `pages_read_user_content`; a
public Page you don't manage needs the *Page Public Content Access* feature,
which requires App Review. **Groups are not available**: Meta removed the Groups
API from all versions on 2024-04-22, so group sources return
`SOURCE_NOT_SUPPORTED`.

```bash
# .env: DATA_PROVIDER=meta, META_ACCESS_TOKEN=..., META_API_VERSION=v25.0
python -m app provider health
python -m app sources add --type page --name "My Page" --identifier <PAGE_ID>
```

Step-by-step setup: [docs/meta-api.md](docs/meta-api.md).

## 11. Tests

```bash
pytest
ruff check app tests
```

The suite needs no network access and no credentials.

## 12. Security

- Secrets live only in environment variables; `.env` is git-ignored.
- `/api/v1/*` requires the bearer key, compared in constant time. Without a
  configured key those endpoints return `503`.
- Tokens, app secrets, API keys and `access_token=` query strings are redacted
  from logs, and httpx request logging is off.
- Requests are validated with Pydantic, bodies are capped (`413`), CORS is
  opt-in, and CSV exports are protected against formula injection.
- Public sources are fetched once per run with a clear User-Agent, timeouts, a
  size cap and bounded retries. `robots.txt` is honoured for advisory pages, and
  HTTP 401/403 is treated as a refusal, never worked around. No login, cookies,
  proxies or IP rotation anywhere.

## 13. Data minimization and terms

Stored per item: source, stable ID, timestamps, text, link, and the matched
locations and hazards. No media, comments, reactions, author profiles, phone
numbers or emails.

- **Open-Meteo** free API is **non-commercial only** (CC BY 4.0, 10,000 calls a day).
- **Google News RSS** is meant for personal feed-reader use; check Google's terms
  for commercial or redistributed use.
- Headlines and links belong to their publishers; only headlines and short
  summaries are stored.

## 14. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/api/v1/*` returns 503 `CONFIGURATION_ERROR` | `INTERNAL_API_KEY` is not set |
| 401 `UNAUTHORIZED` | Header must be exactly `Authorization: Bearer <key>` |
| CSV has only forecast alerts | Nothing hazard-related was published that day, which is normal |
| A source fails with `PERMISSION_DENIED` | The site returned 401/403, or `robots.txt` disallows it. Not bypassed by design |
| `SOURCE_NOT_SUPPORTED` | A Facebook group on the Meta provider |
| `RATE_LIMITED` persists | Wait; the failed window is retried on the next run |
| 409 `COLLECTION_ALREADY_RUNNING` | Another run is active; stale runs expire after `COLLECTION_RUN_STALE_MINUTES` |
| `connection refused` to the database | Start PostgreSQL (`docker compose up -d db`) and check `DATABASE_URL` |
| Port 5432 already in use | Set `POSTGRES_PORT=5433` in `.env` and update `DATABASE_URL` |

## Project structure

```text
app/
  api/            routes/, schemas, dependencies, errors, middleware
  core/           config, logging, security, exceptions, time
  db/             models, session, types, migrate, migrations/
  providers/      base, feeds, advisory_page, weather, meta_graph, mock, routing, http_fetch, retry
  services/       collection, relevance, normalization, deduplication, window, posts, export, seeds, notifications
  cli.py  main.py
docs/             northern-news.md · architecture.md · meta-api.md · n8n.md
data/             sample CSV output
scripts/          run-daily.ps1
tests/            pytest suite
```

## License

MIT, see [LICENSE](LICENSE).
