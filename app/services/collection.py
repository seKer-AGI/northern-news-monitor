"""Collection engine.

For each active source: validate → fetch → filter by window → extract text →
normalize → (news only) relevance filter → dedupe → save, each source in its own
transaction. One failing source never aborts the run, and a source's watermark
only advances after its posts are committed.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.exceptions import CollectionAlreadyRunningError
from app.core.time import Clock, utcnow
from app.db.models import (
    NEWS_SOURCE_TYPES,
    CollectionError,
    CollectionRun,
    Post,
    RunStatus,
    Source,
)
from app.providers.base import FacebookDataProvider, ProviderError, ProviderErrorCode, SourceRef
from app.services.deduplication import CandidatePost, dedupe_batch, filter_new_posts
from app.services.normalization import normalize_text
from app.services.notifications import NotificationProvider, NullNotificationProvider
from app.services.relevance import match_relevance, strip_publisher_suffix
from app.services.window import FetchWindow, compute_window, filter_posts_in_window

logger = logging.getLogger(__name__)

_ADVISORY_LOCK_KEY = 804_217_001  # arbitrary constant for pg_advisory_xact_lock
MISSING_POST_ID = "MISSING_POST_ID"
INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    id: int
    source_type: str
    source_identifier: str
    source_name: str
    source_url: str | None
    last_collected_at: datetime | None


@dataclass(slots=True)
class SourceResult:
    source_id: int
    source_name: str
    status: str
    window_since: datetime | None = None
    window_until: datetime | None = None
    posts_found: int = 0
    posts_saved: int = 0
    posts_skipped: int = 0
    error_code: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class CollectionRunResult:
    run_id: int
    status: str
    provider: str
    started_at: datetime
    completed_at: datetime | None = None
    sources_processed: int = 0
    posts_found: int = 0
    posts_saved: int = 0
    posts_skipped: int = 0
    error_count: int = 0
    error_message: str | None = None
    sources: list[SourceResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class CollectionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: FacebookDataProvider,
        settings: Settings,
        *,
        notifier: NotificationProvider | None = None,
        clock: Clock = utcnow,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.notifier = notifier or NullNotificationProvider()
        self.clock = clock

    # -- public -----------------------------------------------------------
    def run(self, source_ids: list[int] | None = None) -> CollectionRunResult:
        started_at = self.clock()
        run_id = self._start_run(started_at)
        result = CollectionRunResult(
            run_id=run_id,
            status=RunStatus.RUNNING,
            provider=self.provider.name,
            started_at=started_at,
        )
        logger.info("Collection started", extra={"run_id": run_id, "provider": self.provider.name})

        try:
            sources = self._load_sources(source_ids)
            if not sources:
                logger.warning("No active sources configured", extra={"run_id": run_id})
            for source in sources:
                source_result = self._collect_source(run_id, source, started_at)
                result.sources.append(source_result)
                result.sources_processed += 1
                result.posts_found += source_result.posts_found
                result.posts_saved += source_result.posts_saved
                result.posts_skipped += source_result.posts_skipped
            result.status = self._final_status(result.sources)
            failed = [s for s in result.sources if s.status == "failed"]
            if failed:
                result.error_message = f"{len(failed)} of {len(result.sources)} sources failed"
        except Exception as exc:  # unexpected: record and surface as a failed run
            logger.exception("Collection run crashed", extra={"run_id": run_id})
            result.status = RunStatus.FAILED
            result.error_message = f"Unexpected error: {type(exc).__name__}: {exc}"[:1000]
        finally:
            result.completed_at = self.clock()
            result.error_count = self._finish_run(result)

        logger.info(
            "Collection completed",
            extra={
                "run_id": run_id,
                "status": str(result.status),
                "sources_processed": result.sources_processed,
                "posts_found": result.posts_found,
                "posts_saved": result.posts_saved,
                "posts_skipped": result.posts_skipped,
                "error_count": result.error_count,
            },
        )
        try:
            self.notifier.notify_run_completed(result)
        except Exception:
            logger.exception("Notification failed", extra={"run_id": run_id})
        return result

    # -- run bookkeeping --------------------------------------------------
    def _start_run(self, started_at: datetime) -> int:
        with self.session_factory() as session, session.begin():
            if session.get_bind().dialect.name == "postgresql":
                # Serialize concurrent trigger requests across processes.
                session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY})

            stale_before = started_at - timedelta(
                minutes=self.settings.collection_run_stale_minutes
            )
            running = session.scalars(
                select(CollectionRun).where(CollectionRun.status == RunStatus.RUNNING)
            ).all()
            for run in running:
                if run.started_at > stale_before:
                    raise CollectionAlreadyRunningError(
                        f"Collection run {run.id} is already in progress.",
                        details={"run_id": run.id, "started_at": run.started_at.isoformat()},
                    )
                run.status = RunStatus.FAILED
                run.completed_at = started_at
                run.error_message = "Run abandoned (exceeded COLLECTION_RUN_STALE_MINUTES)."

            run = CollectionRun(
                started_at=started_at, status=RunStatus.RUNNING, provider=self.provider.name
            )
            session.add(run)
            session.flush()
            return run.id

    def _finish_run(self, result: CollectionRunResult) -> int:
        with self.session_factory() as session, session.begin():
            run = session.get(CollectionRun, result.run_id)
            assert run is not None
            error_count = len(
                session.scalars(
                    select(CollectionError.id).where(CollectionError.run_id == result.run_id)
                ).all()
            )
            if result.status == RunStatus.FAILED and not result.sources and result.error_message:
                error_count = max(error_count, 1)
            run.status = str(result.status)
            run.completed_at = result.completed_at
            run.sources_processed = result.sources_processed
            run.posts_found = result.posts_found
            run.posts_saved = result.posts_saved
            run.posts_skipped = result.posts_skipped
            run.error_count = error_count
            run.error_message = result.error_message
            return error_count

    def _record_error(
        self, run_id: int, source: _SourceSnapshot | None, code: str, message: str
    ) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                CollectionError(
                    run_id=run_id,
                    source_id=source.id if source else None,
                    source_name=source.source_name if source else None,
                    error_code=code,
                    message=message[:2000],
                )
            )

    @staticmethod
    def _final_status(sources: list[SourceResult]) -> RunStatus:
        if not sources:
            return RunStatus.SUCCESS
        failed = sum(1 for s in sources if s.status == "failed")
        if failed == 0:
            return RunStatus.SUCCESS
        if failed == len(sources):
            return RunStatus.FAILED
        return RunStatus.PARTIAL_SUCCESS

    def _load_sources(self, source_ids: list[int] | None) -> list[_SourceSnapshot]:
        with self.session_factory() as session:
            stmt = select(Source).where(Source.active.is_(True)).order_by(Source.id)
            if source_ids:
                stmt = stmt.where(Source.id.in_(source_ids))
            return [
                _SourceSnapshot(
                    id=s.id,
                    source_type=s.source_type,
                    source_identifier=s.source_identifier,
                    source_name=s.source_name,
                    source_url=s.source_url,
                    last_collected_at=s.last_collected_at,
                )
                for s in session.scalars(stmt)
            ]

    # -- per-source pipeline ----------------------------------------------
    def _collect_source(
        self, run_id: int, source: _SourceSnapshot, run_started_at: datetime
    ) -> SourceResult:
        window = compute_window(
            source.last_collected_at,
            run_started_at,
            overlap_minutes=self.settings.fetch_overlap_minutes,
            initial_lookback_hours=self.settings.initial_lookback_hours,
        )
        result = SourceResult(
            source_id=source.id,
            source_name=source.source_name,
            status="running",
            window_since=window.since,
            window_until=window.until,
        )
        log_ctx = {"run_id": run_id, "source_id": source.id, "source_name": source.source_name}
        logger.info(
            "Processing source",
            extra={**log_ctx, "since": window.since.isoformat(), "until": window.until.isoformat()},
        )
        ref = SourceRef(
            source_type=source.source_type,
            identifier=source.source_identifier,
            name=source.source_name,
            url=source.source_url,
        )

        try:
            validation = self.provider.validate_source(ref)
            if not validation.ok:
                raise ProviderError(
                    validation.error_code or ProviderErrorCode.PROVIDER_ERROR,
                    validation.message or "Source validation failed.",
                )
            raw_posts = self.provider.fetch_posts(ref, window.since, window.until)
            result.posts_found = len(raw_posts)
            logger.info("Posts fetched", extra={**log_ctx, "posts_found": len(raw_posts)})

            candidates, skipped = self._prepare(run_id, source, raw_posts, window, log_ctx)
            saved, duplicates = self._store(source, candidates, window)
            result.posts_saved = saved
            result.posts_skipped = skipped + duplicates
            result.status = "success"
            logger.info(
                "Posts saved",
                extra={**log_ctx, "posts_saved": saved, "duplicates_skipped": duplicates},
            )
        except ProviderError as exc:
            result.status = "failed"
            result.error_code = str(exc.code)
            result.error_message = exc.message
            logger.warning(
                "Source failed",
                extra={**log_ctx, "error_code": str(exc.code), "error": exc.message},
            )
            self._record_error(run_id, source, str(exc.code), exc.message)
        except Exception as exc:
            result.status = "failed"
            result.error_code = INTERNAL_ERROR
            result.error_message = f"{type(exc).__name__}: {exc}"[:1000]
            logger.exception("Source failed with unexpected error", extra=log_ctx)
            self._record_error(run_id, source, INTERNAL_ERROR, result.error_message)
        return result

    def _prepare(
        self,
        run_id: int,
        source: _SourceSnapshot,
        raw_posts: list,
        window: FetchWindow,
        log_ctx: dict,
    ) -> tuple[list[CandidatePost], int]:
        """Filter, extract text, normalize. Returns ``(candidates, skipped_count)``."""
        in_window, outside = filter_posts_in_window(raw_posts, window)
        skipped = len(outside)
        missing_ids = 0
        empty_text = 0
        not_relevant = 0
        is_news = source.source_type in NEWS_SOURCE_TYPES
        candidates: list[CandidatePost] = []

        for post in in_window:
            if not post.external_post_id:
                missing_ids += 1
                continue
            normalized = normalize_text(post.text, remove_urls=self.settings.remove_urls)
            if not normalized:
                empty_text += 1  # e.g. photo-only post; there is no text to collect
                continue
            locations = hazards = None
            if is_news:
                relevance = match_relevance(
                    strip_publisher_suffix(normalized)
                    if source.source_type == "google_news"
                    else normalized
                )
                if not relevance.relevant:
                    not_relevant += 1  # not about northern-areas weather/hazards
                    continue
                locations = "; ".join(relevance.locations)[:500]
                hazards = "; ".join(relevance.hazards)[:500]
            assert post.posted_at is not None  # guaranteed by the window filter
            candidates.append(
                CandidatePost(
                    external_post_id=post.external_post_id,
                    posted_at=post.posted_at,
                    text=normalized,
                    raw_text=post.text if self.settings.store_raw_text else None,
                    url=getattr(post, "url", None),
                    locations=locations,
                    hazards=hazards,
                )
            )

        if missing_ids:
            # Text alone is not a safe identity, so these posts are not stored.
            message = f"{missing_ids} post(s) returned without a stable post ID were skipped."
            logger.warning("Posts without stable ID", extra={**log_ctx, "count": missing_ids})
            self._record_error(run_id, source, MISSING_POST_ID, message)

        unique, batch_duplicates = dedupe_batch(candidates)
        skipped += missing_ids + empty_text + not_relevant + batch_duplicates
        logger.debug(
            "Posts prepared",
            extra={
                **log_ctx,
                "outside_window": len(outside),
                "empty_text": empty_text,
                "not_relevant": not_relevant,
                "batch_duplicates": batch_duplicates,
            },
        )
        return unique, skipped

    def _store(
        self, source: _SourceSnapshot, candidates: list[CandidatePost], window: FetchWindow
    ) -> tuple[int, int]:
        """Insert new posts and advance the source watermark atomically."""
        collected_at = self.clock()
        with self.session_factory() as session, session.begin():
            new_posts, duplicates = filter_new_posts(session, source.id, candidates)
            saved = 0
            for candidate in new_posts:
                try:
                    with session.begin_nested():
                        session.add(
                            Post(
                                source_id=source.id,
                                external_post_id=candidate.external_post_id,
                                source_name=source.source_name,
                                source_type=source.source_type,
                                posted_at=candidate.posted_at,
                                text=candidate.text,
                                raw_text=candidate.raw_text,
                                url=candidate.url,
                                locations=candidate.locations,
                                hazards=candidate.hazards,
                                collected_at=collected_at,
                            )
                        )
                    saved += 1
                except IntegrityError:
                    # Inserted concurrently between the check and the insert.
                    duplicates += 1
            session.execute(
                update(Source)
                .where(Source.id == source.id)
                .values(last_collected_at=window.until, updated_at=Source.updated_at)
            )
        return saved, duplicates
