from datetime import UTC, datetime, timedelta

from app.providers.base import ProviderPost
from app.services.window import FetchWindow, compute_window, filter_posts_in_window

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def test_first_run_uses_initial_lookback():
    window = compute_window(None, NOW, overlap_minutes=10, initial_lookback_hours=24)
    assert window.since == NOW - timedelta(hours=24)
    assert window.until == NOW


def test_incremental_window_starts_at_last_success_minus_overlap():
    last = NOW - timedelta(hours=30)  # e.g. yesterday's run failed: 30h gap, nothing lost
    window = compute_window(last, NOW, overlap_minutes=10, initial_lookback_hours=24)
    assert window.since == last - timedelta(minutes=10)
    assert window.until == NOW


def test_window_bounds_are_exclusive_start_inclusive_end():
    window = FetchWindow(since=NOW - timedelta(hours=1), until=NOW)
    assert not window.contains(NOW - timedelta(hours=1))
    assert window.contains(NOW - timedelta(minutes=59))
    assert window.contains(NOW)
    assert not window.contains(NOW + timedelta(seconds=1))


def test_filter_posts_in_window_splits_and_drops_missing_timestamps():
    window = FetchWindow(since=NOW - timedelta(hours=24), until=NOW)
    inside = ProviderPost("a", NOW - timedelta(hours=2), "recent")
    too_old = ProviderPost("b", NOW - timedelta(hours=48), "old")
    future = ProviderPost("c", NOW + timedelta(minutes=5), "future")
    no_time = ProviderPost("d", None, "no timestamp")

    kept, outside = filter_posts_in_window([inside, too_old, future, no_time], window)
    assert kept == [inside]
    assert outside == [too_old, future, no_time]


def test_naive_timestamps_are_treated_as_utc():
    window = FetchWindow(since=NOW - timedelta(hours=1), until=NOW)
    assert window.contains(datetime(2026, 9, 14, 11, 30))
