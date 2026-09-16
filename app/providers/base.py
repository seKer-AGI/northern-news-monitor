"""Data-provider abstraction.

The collection engine depends only on :class:`DataProvider`. Any
authorized data source (Meta Graph API, a licensed data vendor, a mock) can be
plugged in by implementing this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ProviderErrorCode(StrEnum):
    SOURCE_NOT_SUPPORTED = "SOURCE_NOT_SUPPORTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INVALID_SOURCE = "INVALID_SOURCE"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


RETRYABLE_CODES = frozenset(
    {ProviderErrorCode.RATE_LIMITED, ProviderErrorCode.PROVIDER_UNAVAILABLE}
)


class ProviderError(Exception):
    """Structured, expected provider failure."""

    def __init__(
        self,
        code: ProviderErrorCode,
        message: str,
        *,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.details = details or {}

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Provider-facing view of a configured source (decoupled from the ORM)."""

    source_type: str
    identifier: str
    name: str = ""
    url: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderPost:
    """Minimal post payload. Providers must not return anything beyond this.

    ``url`` is only set by news/weather providers (link to the public article);
    Facebook providers leave it empty.
    """

    external_post_id: str | None
    posted_at: datetime | None
    text: str | None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class SourceValidation:
    ok: bool
    resolved_name: str | None = None
    error_code: ProviderErrorCode | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    ok: bool
    provider: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class DataProvider(ABC):
    name: str = "base"
    supported_source_types: frozenset[str] = frozenset()

    @abstractmethod
    def fetch_posts(
        self, source: SourceRef, since: datetime, until: datetime
    ) -> list[ProviderPost]:
        """Return posts for ``source`` created within ``(since, until]``.

        Providers should make a best effort to honour the window, but callers
        always re-filter, so returning extra posts is safe. Raise
        :class:`ProviderError` for any expected failure.
        """

    @abstractmethod
    def validate_source(self, source: SourceRef) -> SourceValidation:
        """Check the source exists and is readable with current credentials."""

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Check credentials / connectivity without touching any source."""

    def supports(self, source_type: str) -> bool:
        return source_type in self.supported_source_types

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release network resources."""
