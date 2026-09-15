"""Incremental fetch window computation and timestamp filtering."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.time import ensure_utc
from app.providers.base import ProviderPost


@dataclass(frozen=True, slots=True)
class FetchWindow:
    since: datetime  # exclusive
    until: datetime  # inclusive

    def contains(self, moment: datetime) -> bool:
        moment = ensure_utc(moment)
        return self.since < moment <= self.until


def compute_window(
    last_successful: datetime | None,
    run_started_at: datetime,
    *,
    overlap_minutes: int,
    initial_lookback_hours: int,
) -> FetchWindow:
    """Window = (last successful watermark - overlap, run start].

    The upper bound is the run's *start* time, which becomes the next watermark,
    so posts published while the run is in progress are picked up next time.
    If a run fails, the watermark is not advanced and the window is retried.
    """
    until = ensure_utc(run_started_at)
    if last_successful is None:
        since = until - timedelta(hours=initial_lookback_hours)
    else:
        since = ensure_utc(last_successful) - timedelta(minutes=overlap_minutes)
    return FetchWindow(since=min(since, until), until=until)


def filter_posts_in_window(
    posts: Iterable[ProviderPost], window: FetchWindow
) -> tuple[list[ProviderPost], list[ProviderPost]]:
    """Split posts into ``(inside, outside)``. Posts without a timestamp count as outside."""
    inside: list[ProviderPost] = []
    outside: list[ProviderPost] = []
    for post in posts:
        if post.posted_at is not None and window.contains(post.posted_at):
            inside.append(post)
        else:
            outside.append(post)
    return inside, outside
