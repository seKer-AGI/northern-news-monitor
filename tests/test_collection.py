from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.exceptions import CollectionAlreadyRunningError
from app.db.models import CollectionError, CollectionRun, Post, RunStatus, Source
from app.providers.base import ProviderPost
from app.providers.mock import MockFacebookProvider
from app.services.collection import CollectionService


def _service(session_factory, settings, clock, provider=None):
    provider = provider or MockFacebookProvider(clock=clock)
    return CollectionService(session_factory, provider, settings, clock=clock)


def _count(session_factory, model, *where):
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


def test_mock_collection_stores_only_in_window_text_posts(
    session_factory, settings, clock, add_source
):
    add_source("ai-jobs", "group")
    result = _service(session_factory, settings, clock).run()

    assert result.status == RunStatus.SUCCESS
    assert result.posts_saved > 0
    assert result.posts_found == result.posts_saved + result.posts_skipped

    with session_factory() as session:
        posts = session.scalars(select(Post)).all()
    assert len(posts) == result.posts_saved
    for post in posts:
        assert clock.now - timedelta(hours=24) < post.posted_at <= clock.now
        assert post.text and post.text == post.text.strip()
        assert "   " not in post.text
        assert post.raw_text is None  # STORE_RAW_TEXT defaults to false


def test_second_run_creates_no_duplicates(session_factory, settings, clock, add_source):
    add_source("ai-jobs", "group")
    first = _service(session_factory, settings, clock).run()
    clock.advance(minutes=5)
    second = _service(session_factory, settings, clock).run()

    assert first.posts_saved > 0
    assert second.posts_saved == 0
    assert _count(session_factory, Post) == first.posts_saved


def test_incremental_run_collects_only_new_posts(session_factory, settings, clock, add_source):
    source_id = add_source("page-a")
    posts: list[ProviderPost] = [
        ProviderPost("p1", clock.now - timedelta(hours=2), "first post"),
    ]
    provider = MockFacebookProvider(clock=clock, posts_by_source={"page-a": posts})
    _service(session_factory, settings, clock, provider).run()

    clock.advance(hours=24)
    posts.append(ProviderPost("p2", clock.now - timedelta(hours=1), "second post"))
    result = _service(session_factory, settings, clock, provider).run()

    assert result.posts_saved == 1
    assert result.posts_skipped == 1  # p1 is now outside the incremental window
    with session_factory() as session:
        source = session.get(Source, source_id)
        assert source.last_collected_at == clock.now


def test_overlap_window_catches_boundary_posts_without_duplicates(
    session_factory, settings, clock, add_source
):
    add_source("page-a")
    first_run_at = clock.now
    posts = [ProviderPost("p1", first_run_at - timedelta(hours=1), "before boundary")]
    provider = MockFacebookProvider(clock=clock, posts_by_source={"page-a": posts})
    _service(session_factory, settings, clock, provider).run()

    # Post that became visible late, timestamped 5 min before the previous watermark.
    posts.append(ProviderPost("late", first_run_at - timedelta(minutes=5), "late arrival"))
    clock.advance(hours=24)
    result = _service(session_factory, settings, clock, provider).run()

    assert result.posts_saved == 1
    assert _count(session_factory, Post) == 2


def test_failed_source_does_not_stop_other_sources(session_factory, settings, clock, add_source):
    add_source("good-page")
    bad_id = add_source("mock-permission-denied")
    add_source("mock-not-supported", "group")

    result = _service(session_factory, settings, clock).run()

    assert result.status == RunStatus.PARTIAL_SUCCESS
    assert result.error_count == 2
    by_name = {s.source_name: s for s in result.sources}
    assert by_name["Good Page"].status == "success"
    assert by_name["Mock Permission Denied"].error_code == "PERMISSION_DENIED"
    assert by_name["Mock Not Supported"].error_code == "SOURCE_NOT_SUPPORTED"
    assert _count(session_factory, Post) == by_name["Good Page"].posts_saved > 0

    with session_factory() as session:
        run = session.get(CollectionRun, result.run_id)
        assert run.status == "partial_success"
        assert run.completed_at is not None
        errors = session.scalars(select(CollectionError)).all()
        assert {e.error_code for e in errors} == {"PERMISSION_DENIED", "SOURCE_NOT_SUPPORTED"}
        # Watermark is NOT advanced for the failed source, so its window is retried.
        assert session.get(Source, bad_id).last_collected_at is None


def test_all_sources_failing_marks_run_failed(session_factory, settings, clock, add_source):
    add_source("mock-token-expired")
    add_source("mock-invalid")
    result = _service(session_factory, settings, clock).run()
    assert result.status == RunStatus.FAILED
    assert result.error_count == 2


def test_failed_window_is_retried_on_next_run(session_factory, settings, clock, add_source):
    add_source("page-a")
    posts = [ProviderPost("p1", clock.now - timedelta(hours=3), "posted before outage")]

    class Outage(MockFacebookProvider):
        down = True

        def fetch_posts(self, source, since, until):
            if self.down:
                from app.providers.base import ProviderError, ProviderErrorCode

                raise ProviderError(ProviderErrorCode.PROVIDER_UNAVAILABLE, "down")
            return super().fetch_posts(source, since, until)

    provider = Outage(clock=clock, posts_by_source={"page-a": posts})
    assert _service(session_factory, settings, clock, provider).run().status == RunStatus.FAILED

    # 30 hours later the provider recovers; the post is older than "last 24h" but
    # still inside the retried window, so it is not lost.
    clock.advance(hours=30)
    provider.down = False
    settings.initial_lookback_hours = 48
    result = _service(session_factory, settings, clock, provider).run()
    assert result.posts_saved == 1


def test_transient_errors_are_retried_by_provider(session_factory, settings, clock, add_source):
    # The mock's flaky source fails inside fetch_posts; the service itself does not
    # retry (providers own retry policy), so the source fails for this run.
    add_source("mock-flaky")
    provider = MockFacebookProvider(clock=clock, flaky_failures=1)
    first = _service(session_factory, settings, clock, provider).run()
    second = _service(session_factory, settings, clock, provider).run()
    assert first.status == RunStatus.FAILED
    assert second.status == RunStatus.SUCCESS
    assert second.posts_saved > 0


def test_posts_without_stable_id_are_skipped_and_logged(
    session_factory, settings, clock, add_source
):
    add_source("mock-no-id")
    result = _service(session_factory, settings, clock).run()
    assert result.status == RunStatus.SUCCESS
    assert result.posts_saved == 0
    assert result.error_count == 1
    assert (
        _count(session_factory, CollectionError, CollectionError.error_code == "MISSING_POST_ID")
        == 1
    )


def test_store_raw_text_when_enabled(session_factory, settings, clock, add_source):
    add_source("page-a")
    raw = "  Hiring   a data scientist  "
    provider = MockFacebookProvider(
        clock=clock,
        posts_by_source={"page-a": [ProviderPost("p1", clock.now - timedelta(hours=1), raw)]},
    )
    settings.store_raw_text = True
    _service(session_factory, settings, clock, provider).run()
    with session_factory() as session:
        post = session.scalars(select(Post)).one()
    assert post.text == "Hiring a data scientist"
    assert post.raw_text == raw


def test_inactive_sources_are_ignored(session_factory, settings, clock, add_source):
    add_source("page-a", active=False)
    result = _service(session_factory, settings, clock).run()
    assert result.status == RunStatus.SUCCESS
    assert result.sources_processed == 0


def test_run_can_be_limited_to_specific_sources(session_factory, settings, clock, add_source):
    a = add_source("page-a")
    add_source("page-b")
    result = _service(session_factory, settings, clock).run(source_ids=[a])
    assert [s.source_id for s in result.sources] == [a]


def test_concurrent_run_is_rejected(session_factory, settings, clock):
    with session_factory() as session, session.begin():
        session.add(
            CollectionRun(
                started_at=clock.now - timedelta(minutes=5), status="running", provider="mock"
            )
        )
    with pytest.raises(CollectionAlreadyRunningError):
        _service(session_factory, settings, clock).run()


def test_stale_running_run_is_abandoned(session_factory, settings, clock):
    with session_factory() as session, session.begin():
        session.add(
            CollectionRun(
                started_at=clock.now - timedelta(days=1), status="running", provider="mock"
            )
        )
    result = _service(session_factory, settings, clock).run()
    assert result.status == RunStatus.SUCCESS
    with session_factory() as session:
        statuses = session.scalars(select(CollectionRun.status).order_by(CollectionRun.id)).all()
    assert statuses == ["failed", "success"]


def test_unexpected_exception_marks_run_failed(session_factory, settings, clock, add_source):
    add_source("page-a")

    class Broken(MockFacebookProvider):
        def fetch_posts(self, source, since, until):
            raise RuntimeError("boom")

    result = _service(session_factory, settings, clock, Broken(clock=clock)).run()
    assert result.status == RunStatus.FAILED
    assert result.sources[0].error_code == "INTERNAL_ERROR"


def test_timestamps_round_trip_as_utc(session_factory, settings, clock, add_source):
    add_source("page-a")
    posted = datetime(2026, 9, 14, 10, 30, tzinfo=UTC)
    provider = MockFacebookProvider(
        clock=clock, posts_by_source={"page-a": [ProviderPost("p1", posted, "hi")]}
    )
    _service(session_factory, settings, clock, provider).run()
    with session_factory() as session:
        assert session.scalars(select(Post.posted_at)).one() == posted
