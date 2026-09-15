# Architecture

## Layers

| Layer | Package | Responsibility |
|---|---|---|
| API | `app/api` | HTTP routing, request validation, auth, error envelope, body limit |
| Services | `app/services` | Collection pipeline, windowing, normalization, dedup, queries, export, notifications |
| Providers | `app/providers` | Access to an authorized data source behind `FacebookDataProvider` |
| Persistence | `app/db` | SQLAlchemy models, UTC datetime type, sessions, Alembic migrations |
| Core | `app/core` | Settings, structured logging with redaction, security, exceptions, time |

The API and the CLI share the same `CollectionService`, so a run triggered from
n8n over HTTP behaves exactly like `python -m app collect`.

DB and provider I/O use synchronous SQLAlchemy and httpx. FastAPI runs these
endpoints in its threadpool, so the event loop is never blocked. One code path
serves both the API and the CLI. With 5–50 sources a day, async I/O would add
complexity without a measurable benefit.

## Collection pipeline

```text
POST /api/v1/collection/run  |  python -m app collect
        │
        ▼
CollectionService.run()
  1. _start_run      insert collection_runs(status=running)
                     · reject if a non-stale run is active (409)
                     · PostgreSQL: pg_advisory_xact_lock serializes concurrent triggers
  2. _load_sources   active sources (optionally a subset)
  3. for each source (independent — a failure never aborts the run):
       window    = (last_collected_at − overlap, run_started_at]
                   first run: (run_started_at − INITIAL_LOOKBACK_HOURS, run_started_at]
       validate  provider.validate_source()
       fetch     provider.fetch_posts(source, since, until)
       filter    drop posts outside the window / without timestamp
       extract   drop posts without a stable ID (logged + MISSING_POST_ID error row)
       normalize conservative whitespace normalization; drop empty text
       dedupe    in-batch (same ID twice) → against DB → unique constraint (savepoint)
       store     insert posts + advance last_collected_at  ← one transaction
       on error  record collection_errors row; watermark NOT advanced
  4. _finish_run     status = success | partial_success | failed, counters, error_count
  5. notify          NotificationProvider (failure is logged, never fatal)
```

Counters satisfy `posts_found = posts_saved + posts_skipped` for every source.

### Why a per-source watermark

The spec asks for a `last_successful_run` timestamp. A single global timestamp
breaks with partial success. If 48 of 50 sources succeed and the global
timestamp moves forward, the 2 failed sources lose that window permanently. So
each source stores `last_collected_at`, the upper bound of the last window fully
committed for that source. `collection_runs` still records every run for
auditing and monitoring.

The upper bound is the **run start time**, not the completion time. Posts
published while the run is in progress are therefore picked up by the next run.

### Overlap and deduplication

`FETCH_OVERLAP_MINUTES` moves the start of each window slightly earlier. This
catches posts whose timestamps land near the boundary, or that become visible a
little late. Any post fetched twice is dropped by `(source_id, external_post_id)`:

1. `dedupe_batch`: the same ID appearing twice in one response.
2. `filter_new_posts`: IDs already stored for this source.
3. The database `UNIQUE (source_id, external_post_id)` constraint. Each insert
   runs in a SAVEPOINT, so a concurrent duplicate is counted as skipped rather
   than failing the transaction.

Text is never used as an identity. Two different people can post identical text.

## Data model

```text
sources ──< posts                 (ON DELETE CASCADE)
   │
   └──< collection_errors >── collection_runs   (errors: source ON DELETE SET NULL)
```

- **sources**: `id, source_type(page|group), source_name, source_identifier,
  source_url, active, last_collected_at, created_at, updated_at`.
  `UNIQUE(source_type, source_identifier)`.
- **posts**: `id, source_id, external_post_id, source_name, source_type,
  posted_at, text, raw_text?, collected_at, created_at`.
  `UNIQUE(source_id, external_post_id)`, indexes on `posted_at` and `source_id`.
- **collection_runs**: `id, started_at, completed_at, status, provider,
  sources_processed, posts_found, posts_saved, posts_skipped, error_count,
  error_message`.
- **collection_errors**: `id, run_id, source_id, source_name, error_code,
  message, created_at`.

All timestamps are timezone-aware UTC. `UTCDateTime` rejects naive datetimes on
write.

## Error model

Providers raise `ProviderError(code, message)`:

| Code | Retried? | Meaning |
|---|---|---|
| `SOURCE_NOT_SUPPORTED` | no | Provider cannot read this source type (e.g. groups on Meta) |
| `PERMISSION_DENIED` | no | Token lacks permission / app review |
| `INVALID_SOURCE` | no | Source does not exist or is not visible |
| `TOKEN_EXPIRED` | no | Credentials expired or invalid |
| `RATE_LIMITED` | yes (bounded) | Provider throttling |
| `PROVIDER_UNAVAILABLE` | yes (bounded) | Timeout, network error, 5xx, transient error |
| `PROVIDER_ERROR` | no | Any other provider error |
| `CONFIGURATION_ERROR` | no | Provider misconfigured |

The service adds `MISSING_POST_ID` (non-fatal) and `INTERNAL_ERROR` (an
unexpected exception for a single source).

Retries use capped exponential backoff with small jitter
(`PROVIDER_MAX_RETRIES`, `PROVIDER_BACKOFF_*`). There is deliberately no
credential, IP, or cookie rotation. When retries run out, the source fails for
this run and its window is retried on the next run.

## Adding a provider

1. Implement `app.providers.base.FacebookDataProvider`:
   - `fetch_posts(source, since, until) -> list[ProviderPost]`
   - `validate_source(source) -> SourceValidation`
   - `health_check() -> ProviderHealth`
   - set `name` and `supported_source_types`
2. Return only `ProviderPost(external_post_id, posted_at, text)`. Don't fetch or
   return any other fields.
3. Map the provider's failures to `ProviderError` codes. Use
   `providers.retry.call_with_retry` for transient errors.
4. Register it in `app/providers/factory.py` and add a `DATA_PROVIDER` value.
5. Test it with `httpx.MockTransport`, like `tests/test_meta_provider.py`.

Only plug in providers whose collection method and your intended use are
explicitly permitted by the platform's terms and applicable law.

## Adding a notifier

Implement `app.services.notifications.NotificationProvider.notify_run_completed`
(email, Slack, Telegram, and so on) and register it in `build_notifier`.
