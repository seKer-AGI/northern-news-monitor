"""Time helpers. All timestamps in this application are timezone-aware UTC."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as aware UTC. Naive datetimes are interpreted as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    """Format as ISO 8601 with a trailing ``Z`` (e.g. ``2026-09-14T10:30:00Z``)."""
    value = ensure_utc(value).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def parse_date_param(value: str, *, is_end: bool = False) -> datetime:
    """Parse a user-supplied date filter.

    Accepts a full ISO 8601 datetime or a bare ``YYYY-MM-DD`` date. A bare date
    used as an *end* bound expands to the end of that day, so
    ``end_date=2026-09-14`` includes posts from the whole of the 14th.
    """
    raw = value.strip()
    if len(raw) == 10:
        day = date.fromisoformat(raw)
        start = datetime.combine(day, time.min, tzinfo=UTC)
        return start + timedelta(days=1) - timedelta(microseconds=1) if is_end else start
    return ensure_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
