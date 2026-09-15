# Facebook Post Monitor

Collects **only the text** of newly published posts from a configurable list of
Facebook sources, using an **official or otherwise explicitly authorized data
provider**. It's built to run once every 24 hours from n8n, cron, or Docker.

```text
Sources → Authorized provider → Fetch → Filter by window → Extract text
        → Normalize → Deduplicate → PostgreSQL → CSV / JSON → (notification)
```

> **Read this first.** Access to Facebook data depends entirely on Meta's
> *current* permissions, endpoints, App Review requirements and your
> authorization for each source. This project does **not** log in to Facebook,
> automate a browser, scrape HTML, or bypass any access control, rate limit, or
> CAPTCHA. Arbitrary Facebook Groups **cannot** be read through the official
> API. See [Meta API limitations](#3-important-facebookmeta-api-limitations).

---

## Contents

1. [What the project does](#1-what-the-project-does)
2. [Architecture](#2-architecture)
3. [Important Facebook/Meta API limitations](#3-important-facebookmeta-api-limitations)
4. [Supported data sources](#4-supported-data-sources)
5. [Installation](#5-installation)
6. [Environment variables](#6-environment-variables)
7. [PostgreSQL setup](#7-postgresql-setup)
8. [Database migrations](#8-database-migrations)
9. [Running locally](#9-running-locally)
10. [Running tests](#10-running-tests)
11. [Running the collector](#11-running-the-collector)
12. [API documentation](#12-api-documentation)
13. [n8n integration](#13-n8n-integration)
14. [Docker deployment](#14-docker-deployment)
15. [Security](#15-security)
16. [Data minimization](#16-data-minimization)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. What the project does

- Keeps a list of 5–50 **sources** (Facebook Pages or Groups) in PostgreSQL.
- On each run, asks the configured **data provider** for posts published since
  that source was last collected successfully.
- Stores **only** the post text, the source's name and type, the post ID, and timestamps.
- Never inserts a post twice (unique `source_id + external_post_id`).
- Records every run, including partial failures, in `collection_runs` and
  `collection_errors`.
- Exposes a REST API, a CLI, and CSV/JSON exports.

It ships with two providers:

| Provider | `DATA_PROVIDER` | Purpose |
|---|---|---|
| `MockFacebookProvider` | `mock` (default) | Realistic fake posts. The whole pipeline works without any Facebook credentials. |
| `MetaGraphAPIProvider` | `meta` | Official Meta Graph API, using documented endpoints only. |

## 2. Architecture

```text
                ┌────────────────────┐
 n8n / cron ───▶│ POST /collection/run│──┐
                │ python -m app collect │  │
                └────────────────────┘  ▼
                               ┌──────────────────┐     ┌───────────────────────┐
                               │ CollectionService │───▶│ FacebookDataProvider  │
                               └────────┬─────────┘     │  ├ MetaGraphAPIProvider│
                                        │               │  └ MockFacebookProvider│
          window · normalize · dedupe   │               └───────────────────────┘
                                        ▼
                               ┌──────────────────┐
                               │   PostgreSQL     │ sources · posts ·
                               │                  │ collection_runs · collection_errors
                               └────────┬─────────┘
                                        ▼
                             REST API · CSV · JSON
```

Layers are kept separate: `app/api` (HTTP), `app/services` (business logic),
`app/providers` (data access), `app/db` (persistence), `app/core` (config,
logging, security). See [docs/architecture.md](docs/architecture.md).

**Incremental collection.** Each source keeps a watermark (`last_collected_at`).
A run fetches `(watermark − FETCH_OVERLAP_MINUTES, run start]`. The watermark
moves forward only after that source's posts are committed. If a run fails, or a
single source fails, the next run retries the whole missed window, so no posts
are lost even when the job doesn't run for 30 hours. Posts caught again by the
overlap are removed by post ID.

## 3. Important Facebook/Meta API limitations

The following reflects Meta's documentation at the time of writing. **Always
check the current [Graph API changelog](https://developers.facebook.com/docs/graph-api/changelog).**

| Situation | What Meta requires | Supported here? |
|---|---|---|
| **A Page you manage** | Page access token with `pages_read_engagement` and `pages_read_user_content` | ✅ `MetaGraphAPIProvider` |
| **A public Page you don't manage** | The *Page Public Content Access* feature, which requires Meta App Review | ✅ Only if your app has been approved |
| **A Facebook Group** (even one you've joined) | The Groups API was deprecated in v19.0 and **removed from all versions on 2024‑04‑22** | ❌ Returns `SOURCE_NOT_SUPPORTED` |

- Creating a Meta developer app doesn't grant access to anybody else's content.
- The Graph API has no subscription fee, but access is governed by permissions,
  App Review, and rate limits.
- When a source can't be read, the provider returns a **structured error** such as
  `PERMISSION_DENIED`, `SOURCE_NOT_SUPPORTED`, or `TOKEN_EXPIRED`. That source is
  marked failed and every other source keeps working.
- For Groups, the only legitimate route is a **different, explicitly authorized
  data provider**. Implement `FacebookDataProvider` for it (see
  [docs/architecture.md](docs/architecture.md#adding-a-provider)).

Full details and the step-by-step setup are in [docs/meta-api.md](docs/meta-api.md).

## 4. Supported data sources

| `source_type` | Mock provider | Meta Graph API provider |
|---|---|---|
| `page` | ✅ | ✅ with the permissions above |
| `group` | ✅ (fake data) | ❌ `SOURCE_NOT_SUPPORTED` |

`source_identifier` is the numeric Page/Group ID or the Page username.

## 5. Installation

Requirements: Python 3.12+, and PostgreSQL 14+ (or Docker).

```bash
git clone <your-repo-url> facebook-post-monitor
cd facebook-post-monitor
python -m venv .venv
# Linux/macOS:  source .venv/bin/activate
# Windows:      .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env          # Windows: copy .env.example .env
```

Generate an internal API key and put it in `.env` as `INTERNAL_API_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 6. Environment variables

All configuration comes from environment variables or `.env`. Secrets are never
hard-coded, logged, or returned by the API.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://fpm:fpm@localhost:5432/facebook_post_monitor` | SQLAlchemy URL |
| `DATA_PROVIDER` | `mock` | `mock` or `meta` |
| `META_ACCESS_TOKEN` | – | **Required if `meta`.** Page access token |
| `META_API_VERSION` | – | **Required if `meta`.** e.g. `v25.0` |
| `META_APP_ID` | – | Optional, for your own reference |
| `META_APP_SECRET` | – | Optional. Enables `appsecret_proof` |
| `META_PAGE_SIZE` | `100` | Posts per request (Meta maximum: 100) |
| `META_MAX_PAGES` | `10` | Pagination cap per source per run |
| `HTTP_TIMEOUT_SECONDS` | `30` | Provider request timeout |
| `PROVIDER_MAX_RETRIES` | `3` | Retries for rate limits and transient errors |
| `PROVIDER_BACKOFF_BASE_SECONDS` | `2` | Exponential backoff base |
| `PROVIDER_BACKOFF_MAX_SECONDS` | `60` | Backoff cap |
| `FETCH_OVERLAP_MINUTES` | `10` | Overlap with the previous window |
| `INITIAL_LOOKBACK_HOURS` | `24` | Window for a source's first run |
| `COLLECTION_RUN_STALE_MINUTES` | `180` | A `running` run older than this is treated as abandoned |
| `STORE_RAW_TEXT` | `false` | Also store the un-normalized text |
| `REMOVE_URLS` | `false` | Strip URLs during normalization |
| `NOTIFICATION_PROVIDER` | `console` | `console` or `none` |
| `INTERNAL_API_KEY` | – | **Required for `/api/v1/*`.** Bearer token |
| `CORS_ALLOWED_ORIGINS` | *(empty)* | Comma-separated origins; empty disables CORS |
| `MAX_REQUEST_BODY_BYTES` | `1048576` | Larger requests get `413` |
| `CSV_ESCAPE_FORMULAS` | `true` | Prefix `= + - @` cells with `'` in CSV exports |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | `json` or `text` |

When a required variable is missing, the app says exactly which one, for example:
`Missing required environment variables: META_ACCESS_TOKEN, META_API_VERSION`.

## 7. PostgreSQL setup

**Using Docker** (simplest):

```bash
docker compose up -d db
```

**Using a native install:**

```sql
CREATE USER fpm WITH PASSWORD 'change-me';
CREATE DATABASE facebook_post_monitor OWNER fpm;
```

Then set `DATABASE_URL=postgresql+psycopg://fpm:change-me@localhost:5432/facebook_post_monitor`.

## 8. Database migrations

```bash
python -m app db migrate            # upgrade to latest
python -m app db current            # show current revision
python -m app db downgrade          # revert one revision
alembic upgrade head                # plain Alembic works too (reads DATABASE_URL)
```

## 9. Running locally

```bash
python -m app serve --reload        # http://127.0.0.1:8000/docs
```

Quick start with the mock provider:

```bash
python -m app sources add --type group --name "AI Jobs"   --identifier ai-jobs
python -m app sources add --type page  --name "Dev Hiring" --identifier dev-hiring
python -m app collect               # stores posts
python -m app collect               # posts_saved: 0 (no duplicates)
python -m app export csv -o posts.csv
```

The mock provider also has identifiers that simulate failures:
`mock-permission-denied`, `mock-not-supported`, `mock-invalid`,
`mock-token-expired`, `mock-rate-limited`, `mock-unavailable`, `mock-flaky`, and
`mock-no-id`.

## 10. Running tests

```bash
pytest                              # no Facebook credentials or network needed
pytest --cov=app --cov-report=term-missing
ruff check app tests
```

Tests use a temporary SQLite database, so they don't need PostgreSQL. A
migration test checks that the Alembic schema matches the ORM models.

## 11. Running the collector

```bash
python -m app collect                       # all active sources
python -m app collect --source-id 3         # one source (repeatable)
python -m app runs list                     # recent runs
```

Exit codes: `0` success, `3` partial success, `1` failed, `2` configuration or usage error.
The run summary is printed as JSON on stdout. Logs go to stderr.

Cron example (daily at 06:00):

```cron
0 6 * * * cd /srv/facebook-post-monitor && .venv/bin/python -m app collect >> collect.log 2>&1
```

## 12. API documentation

Interactive docs: `http://localhost:8000/docs` (Swagger) and `/redoc`.

Every `/api/v1/*` endpoint needs `Authorization: Bearer <INTERNAL_API_KEY>`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness + DB check (public) |
| GET | `/api/v1/provider/health` | Verify provider credentials |
| GET | `/api/v1/sources` | List sources (`?active=`, `?source_type=`) |
| POST | `/api/v1/sources` | Create source |
| GET | `/api/v1/sources/{id}` | Get source |
| PATCH | `/api/v1/sources/{id}` | Update `source_name`, `source_url`, `active` |
| DELETE | `/api/v1/sources/{id}` | Delete source **and its posts** (use `active=false` to pause) |
| POST | `/api/v1/sources/{id}/validate` | Check the provider can read it |
| POST | `/api/v1/collection/run` | Run collection now (optional body `{"source_ids": [1,2]}`) |
| GET | `/api/v1/collection/runs` | Paginated run history (`?status=`) |
| GET | `/api/v1/collection/runs/{id}` | Run detail with errors |
| GET | `/api/v1/posts` | Paginated posts |
| GET | `/api/v1/posts/{id}` | Single post |
| GET | `/api/v1/export/csv` | CSV: `source_name, source_type, posted_at, text` |
| GET | `/api/v1/export/json` | JSON with the same four fields |

Post filters (for `/posts` and both exports): `source_id`, `source_type`,
`start_date`, `end_date`. Dates can be ISO 8601 datetimes or `YYYY-MM-DD`. A bare
`end_date` includes the whole day. Pagination uses `page` and `page_size` (max 200).

`POST /api/v1/collection/run` status codes: **200** for `success` or
`partial_success` (check `status`), **502** if the run failed, **409** if a run is
already in progress, **401** for a bad key.

```bash
curl -X POST http://localhost:8000/api/v1/sources \
  -H "Authorization: Bearer $INTERNAL_API_KEY" -H "Content-Type: application/json" \
  -d '{"source_type":"page","source_name":"Example Page","source_identifier":"examplepage"}'

curl -X POST http://localhost:8000/api/v1/collection/run -H "Authorization: Bearer $INTERNAL_API_KEY"

curl "http://localhost:8000/api/v1/posts?source_type=page&start_date=2026-09-14" \
  -H "Authorization: Bearer $INTERNAL_API_KEY"
```

Example post:

```json
{
  "id": 123,
  "source_id": 1,
  "source_name": "Example Group",
  "source_type": "group",
  "external_post_id": "123_456",
  "posted_at": "2026-09-14T10:30:00Z",
  "text": "Looking for an AI developer...",
  "collected_at": "2026-09-15T06:00:04Z"
}
```

Errors always use this shape:
`{"error": {"code": "SOURCE_NOT_SUPPORTED", "message": "...", "details": {}}}`.

## 13. n8n integration

```text
Schedule Trigger (daily) → HTTP Request POST /api/v1/collection/run → IF status == success → (notify)
```

See [docs/n8n.md](docs/n8n.md) for step-by-step node configuration, timezone
and authentication setup, and an importable workflow.

## 14. Docker deployment

```bash
cp .env.example .env    # set INTERNAL_API_KEY (and Meta variables if DATA_PROVIDER=meta)
docker compose up -d --build
docker compose exec api python -m app sources add --type page --name "Example" --identifier examplepage
docker compose exec api python -m app collect
curl http://localhost:8000/health
```

The `api` container applies migrations on startup and runs as a non-root user.
n8n is intentionally not part of this compose file, so the service can be
deployed on its own. Change `POSTGRES_PASSWORD` for anything beyond local use.

## 15. Security

- Secrets live only in environment variables. `.env` is git-ignored and
  `.env.example` has no values.
- Every `/api/v1/*` endpoint requires the internal bearer key, compared in
  constant time. If no key is configured, those endpoints return `503`.
- The Meta token, app secret, API key, `access_token=` / `appsecret_proof=` query
  strings and `Bearer` headers are **redacted from all logs**. httpx request
  logging is disabled because Graph URLs contain tokens.
- The access token is never sent to a pagination URL on a non-Graph host.
- Requests are validated with Pydantic: unknown fields are rejected, and
  identifier and URL formats are enforced. Bodies are capped (`413`), CORS is
  opt-in, and CSV exports are protected against formula injection.
- Retries are bounded and only apply to transient errors. No IP, account, or
  cookie rotation, and no CAPTCHA handling.

## 16. Data minimization

Stored per post: `source_id`, `external_post_id`, `source_name`, `source_type`,
`posted_at`, `text`, `collected_at`, `created_at`. `raw_text` is stored only if
`STORE_RAW_TEXT=true`.

**Never collected:** images, videos or media URLs, comments, reactions, likes,
shares, author profiles, phone numbers, or emails. The Meta provider requests
only `fields=id,message,created_time`. Exports contain just
`source_name, source_type, posted_at, text`. Posts with no text (for example,
photo-only posts) are skipped.

## 17. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Missing required environment variables: META_ACCESS_TOKEN…` | Set them in `.env`, or use `DATA_PROVIDER=mock` |
| `/api/v1/*` returns 503 `CONFIGURATION_ERROR` | `INTERNAL_API_KEY` is not set |
| 401 `UNAUTHORIZED` | The header must be exactly `Authorization: Bearer <key>` |
| Source fails with `SOURCE_NOT_SUPPORTED` | A group source on the Meta provider. Meta removed the Groups API |
| `PERMISSION_DENIED` | The token lacks `pages_read_engagement` / `pages_read_user_content`, or Page Public Content Access isn't approved |
| `TOKEN_EXPIRED` | Generate a new token. See [docs/meta-api.md](docs/meta-api.md#tokens) |
| `INVALID_SOURCE` | Wrong Page ID/username, or the object isn't visible to your token |
| `RATE_LIMITED` persists | Reduce sources or pages per run and wait. The failed window is retried next run |
| 409 `COLLECTION_ALREADY_RUNNING` | Another run is active. Stale runs auto-expire after `COLLECTION_RUN_STALE_MINUTES` |
| `MISSING_POST_ID` error rows | The provider returned posts without IDs. They are skipped rather than deduplicated by text |
| `connection refused` to the DB | Start PostgreSQL (`docker compose up -d db`) and check `DATABASE_URL` |
| Port 5432 already in use | Set `POSTGRES_PORT=5433` in `.env` and adjust `DATABASE_URL` |
| n8n in Docker can't reach the API | Use `http://host.docker.internal:8000` rather than `localhost` |

## Project structure

```text
app/
  api/            routes/, schemas, dependencies, errors, middleware
  core/           config, logging, security, exceptions, time
  db/             models, session, types, migrate, migrations/
  providers/      base, meta_graph, mock, retry, factory
  services/       collection, normalization, deduplication, window, posts, export, notifications
  cli.py  main.py
docs/             architecture.md · meta-api.md · n8n.md · n8n-workflow.json
tests/            pytest suite (no credentials required)
```

## License

MIT, see [LICENSE](LICENSE).
