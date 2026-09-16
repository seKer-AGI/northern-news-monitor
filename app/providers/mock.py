"""Deterministic mock provider for local development and tests.

Posts are anchored to a fixed time grid, so repeated runs return the *same*
post IDs — exactly like a real API — which lets you verify deduplication.

Each batch deliberately includes:
  * posts older than the requested window (exercises timestamp filtering),
  * a duplicated post in the same response (exercises in-batch dedup),
  * a media-only post with no text (exercises the text-only rule),
  * messy whitespace, emoji and non-Latin text (exercises normalization).

Special identifiers simulate failures:
  mock-permission-denied, mock-not-supported, mock-invalid, mock-token-expired,
  mock-rate-limited, mock-unavailable, mock-flaky (fails twice then succeeds),
  mock-no-id (posts without a stable ID).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from app.core.time import Clock, utcnow
from app.providers.base import (
    DataProvider,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
    ProviderPost,
    SourceRef,
    SourceValidation,
)

MOCK_TEXTS: tuple[str, ...] = (
    "Looking for an AI engineer to build a chatbot.",
    "Does anyone recommend a Python developer?",
    "We need help automating our sales workflow.",
    "Hiring a data scientist for a remote project.",
    "  Anyone know a good   web developer in Islamabad?  \n\n\n\nDM me please 🙏  ",
    "Need a freelancer for n8n automations —\r\nbudget is flexible 💼",
    "کیا کوئی اچھا موبائل ایپ ڈویلپر جانتا ہے؟",
    "Startup looking for a technical co-founder (React + FastAPI). https://example.com/job",
)

_FAILURES: dict[str, tuple[ProviderErrorCode, str]] = {
    "mock-permission-denied": (
        ProviderErrorCode.PERMISSION_DENIED,
        "The access token does not have permission to read this source.",
    ),
    "mock-not-supported": (
        ProviderErrorCode.SOURCE_NOT_SUPPORTED,
        "This source cannot be read through the configured provider.",
    ),
    "mock-invalid": (ProviderErrorCode.INVALID_SOURCE, "Source does not exist."),
    "mock-token-expired": (ProviderErrorCode.TOKEN_EXPIRED, "Access token has expired."),
    "mock-rate-limited": (ProviderErrorCode.RATE_LIMITED, "Rate limit reached."),
    "mock-unavailable": (ProviderErrorCode.PROVIDER_UNAVAILABLE, "Provider temporarily down."),
}


def _stable_int(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:12], 16)


class MockFacebookProvider(DataProvider):
    name = "mock"
    supported_source_types = frozenset({"page", "group"})

    def __init__(
        self,
        *,
        clock: Clock = utcnow,
        slot_hours: int = 4,
        history_hours: int = 72,
        posts_by_source: dict[str, list[ProviderPost]] | None = None,
        flaky_failures: int = 2,
    ) -> None:
        self.clock = clock
        self.slot_hours = slot_hours
        self.history_hours = history_hours
        self.posts_by_source = posts_by_source
        self.flaky_failures = flaky_failures
        self.fetch_calls: defaultdict[str, int] = defaultdict(int)

    # -- interface --------------------------------------------------------
    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            ok=True, provider=self.name, message="Mock provider is always healthy."
        )

    def validate_source(self, source: SourceRef) -> SourceValidation:
        failure = _FAILURES.get(source.identifier)
        if failure and failure[0] not in (
            ProviderErrorCode.RATE_LIMITED,
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
        ):
            return SourceValidation(ok=False, error_code=failure[0], message=failure[1])
        if not self.supports(source.source_type):
            return SourceValidation(
                ok=False,
                error_code=ProviderErrorCode.SOURCE_NOT_SUPPORTED,
                message=f"Source type {source.source_type!r} is not supported.",
            )
        return SourceValidation(ok=True, resolved_name=source.name or source.identifier)

    def fetch_posts(
        self, source: SourceRef, since: datetime, until: datetime
    ) -> list[ProviderPost]:
        self.fetch_calls[source.identifier] += 1
        if source.identifier in _FAILURES:
            code, message = _FAILURES[source.identifier]
            raise ProviderError(code, message)
        if source.identifier == "mock-flaky" and (
            self.fetch_calls[source.identifier] <= self.flaky_failures
        ):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE, "Simulated transient failure."
            )

        if self.posts_by_source is not None:
            return list(self.posts_by_source.get(source.identifier, []))
        return self._generate(source)

    # -- generation -------------------------------------------------------
    def _generate(self, source: SourceRef) -> list[ProviderPost]:
        now = self.clock()
        slot = self.slot_hours * 3600
        latest_slot = int(now.timestamp()) // slot * slot
        omit_id = source.identifier == "mock-no-id"

        posts: list[ProviderPost] = []
        for k in range(self.history_hours // self.slot_hours + 1):
            slot_start = latest_slot - k * slot
            seed = _stable_int(source.identifier, str(slot_start))
            posted_at = datetime.fromtimestamp(slot_start, UTC) + timedelta(
                minutes=seed % (self.slot_hours * 60)
            )
            if posted_at > now:
                continue
            posts.append(
                ProviderPost(
                    external_post_id=None if omit_id else f"{source.identifier}_{slot_start}",
                    posted_at=posted_at,
                    text=MOCK_TEXTS[seed % len(MOCK_TEXTS)],
                )
            )

        if posts:
            posts.append(posts[0])  # duplicate within the same response
            newest = posts[0]
            posts.append(
                ProviderPost(
                    external_post_id=None if omit_id else f"{newest.external_post_id}_media",
                    posted_at=newest.posted_at,
                    text=None,  # photo/video-only post: no text to collect
                )
            )
        return posts
