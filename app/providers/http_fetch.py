"""Polite HTTP fetching for public news/weather sources.

Identifies itself with a clear User-Agent, uses timeouts, caps response size,
retries only transient failures with bounded backoff, and treats 401/403 as a
refusal to respect — never something to work around.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.providers.base import ProviderError, ProviderErrorCode
from app.providers.retry import RetryPolicy, call_with_retry


@dataclass(frozen=True, slots=True)
class FetchResult:
    status_code: int
    url: str
    content: bytes
    headers: dict[str, str]


def map_http_error(status_code: int, headers: httpx.Headers | dict[str, str]) -> ProviderError:
    details = {"http_status": status_code}
    if status_code in (401, 403):
        return ProviderError(
            ProviderErrorCode.PERMISSION_DENIED,
            f"The source refused access (HTTP {status_code}).",
            details=details,
        )
    if status_code in (404, 410):
        return ProviderError(
            ProviderErrorCode.INVALID_SOURCE,
            f"Source URL not found (HTTP {status_code}).",
            details=details,
        )
    if status_code == 429:
        retry_after = headers.get("retry-after")
        return ProviderError(
            ProviderErrorCode.RATE_LIMITED,
            "The source is rate limiting requests (HTTP 429).",
            retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
            details=details,
        )
    if status_code >= 500:
        return ProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
            f"The source is temporarily unavailable (HTTP {status_code}).",
            details=details,
        )
    return ProviderError(
        ProviderErrorCode.PROVIDER_ERROR, f"Unexpected HTTP {status_code}.", details=details
    )


class HttpFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float,
        retry: RetryPolicy,
        max_bytes: int,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._retry = retry
        self._max_bytes = max_bytes
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._client.headers["User-Agent"] = user_agent

    def get(
        self, url: str, params: dict[str, Any] | None = None, *, operation: str = "fetch"
    ) -> FetchResult:
        if not url.lower().startswith(("http://", "https://")):
            raise ProviderError(ProviderErrorCode.INVALID_SOURCE, "Source URL must be http(s).")

        def attempt() -> FetchResult:
            try:
                with self._client.stream("GET", url, params=params, follow_redirects=True) as resp:
                    if resp.status_code >= 400:
                        raise map_http_error(resp.status_code, resp.headers)
                    size = 0
                    chunks: list[bytes] = []
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > self._max_bytes:
                            raise ProviderError(
                                ProviderErrorCode.PROVIDER_ERROR,
                                f"Response larger than {self._max_bytes} bytes; ignored.",
                            )
                        chunks.append(chunk)
                    return FetchResult(
                        status_code=resp.status_code,
                        url=str(resp.url),
                        content=b"".join(chunks),
                        headers=dict(resp.headers),
                    )
            except httpx.TooManyRedirects as exc:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_ERROR, "Too many redirects."
                ) from exc
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_UNAVAILABLE, "Request timed out."
                ) from exc
            except httpx.RequestError as exc:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_UNAVAILABLE, f"Network error ({type(exc).__name__})."
                ) from exc

        return call_with_retry(attempt, self._retry, sleep=self._sleep, operation=operation)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
