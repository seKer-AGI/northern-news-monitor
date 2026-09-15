"""Meta Graph API provider.

Only documented Graph API functionality is used:

* ``GET /{page-id}/posts?fields=id,message,created_time&since=&until=&limit=``
  (Page posts edge; cursor pagination via ``paging.next``; ``limit`` max 100)
* ``GET /{page-id}?fields=id,name``  (source validation)
* ``GET /me?fields=id,name``          (token health check)
* ``appsecret_proof`` (HMAC-SHA256 of the token keyed by the app secret)

Access requirements (per Meta documentation, subject to change):

* Pages you manage: a Page access token with ``pages_read_engagement`` and
  ``pages_read_user_content``.
* Public Pages you do not manage: the "Page Public Content Access" feature,
  which requires Meta App Review.
* Groups: the Facebook Groups API was deprecated in Graph API v19.0 and removed
  from all versions on 2024-04-22. Group sources therefore always return
  ``SOURCE_NOT_SUPPORTED`` from this provider — no workaround is attempted.

Error codes follow https://developers.facebook.com/docs/graph-api/guides/error-handling
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.core.time import ensure_utc
from app.providers.base import (
    FacebookDataProvider,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
    ProviderPost,
    SourceRef,
    SourceValidation,
)
from app.providers.retry import RetryPolicy, call_with_retry

logger = logging.getLogger(__name__)

GROUPS_NOT_SUPPORTED_MESSAGE = (
    "Facebook Groups cannot be read through the Meta Graph API: the Groups API was "
    "deprecated in v19.0 and removed from all API versions on 2024-04-22. Use a Page "
    "source, or plug in a different explicitly authorized data provider."
)

_RATE_LIMIT_CODES = {4, 17, 32, 613} | set(range(80001, 80015))
_TRANSIENT_CODES = {1, 2}
_TOKEN_CODES = {102, 190}


def _parse_created_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return ensure_utc(datetime.fromisoformat(value))
    except ValueError:
        try:
            return ensure_utc(datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z"))
        except ValueError:
            return None


class MetaGraphAPIProvider(FacebookDataProvider):
    name = "meta_graph"
    supported_source_types = frozenset({"page"})

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if settings.meta_access_token is None or not settings.meta_api_version:
            raise ProviderError(
                ProviderErrorCode.CONFIGURATION_ERROR,
                "META_ACCESS_TOKEN and META_API_VERSION must be set to use the Meta provider.",
            )
        self._token = settings.meta_access_token.get_secret_value()
        self._app_secret = (
            settings.meta_app_secret.get_secret_value() if settings.meta_app_secret else None
        )
        self._base_url = f"{settings.meta_graph_base_url.rstrip('/')}/{settings.meta_api_version}"
        self._host = httpx.URL(settings.meta_graph_base_url).host
        self._page_size = settings.meta_page_size
        self._max_pages = settings.meta_max_pages
        self._retry = RetryPolicy(
            max_retries=settings.provider_max_retries,
            base_delay=settings.provider_backoff_base_seconds,
            max_delay=settings.provider_backoff_max_seconds,
        )
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": "facebook-post-monitor/0.1"},
        )

    # -- interface --------------------------------------------------------
    def health_check(self) -> ProviderHealth:
        try:
            body = self._get(f"{self._base_url}/me", {"fields": "id,name"}, "health_check")
        except ProviderError as exc:
            return ProviderHealth(
                ok=False, provider=self.name, message=exc.message, details={"error_code": exc.code}
            )
        return ProviderHealth(
            ok=True,
            provider=self.name,
            message="Access token is valid.",
            details={"token_subject_id": body.get("id"), "token_subject_name": body.get("name")},
        )

    def validate_source(self, source: SourceRef) -> SourceValidation:
        if not self.supports(source.source_type):
            return SourceValidation(
                ok=False,
                error_code=ProviderErrorCode.SOURCE_NOT_SUPPORTED,
                message=self._unsupported_message(source.source_type),
            )
        try:
            body = self._get(self._node_url(source.identifier), {"fields": "id,name"}, "validate")
        except ProviderError as exc:
            return SourceValidation(ok=False, error_code=exc.code, message=exc.message)
        return SourceValidation(ok=True, resolved_name=body.get("name"))

    def fetch_posts(
        self, source: SourceRef, since: datetime, until: datetime
    ) -> list[ProviderPost]:
        if not self.supports(source.source_type):
            raise ProviderError(
                ProviderErrorCode.SOURCE_NOT_SUPPORTED,
                self._unsupported_message(source.source_type),
            )

        url: str | None = f"{self._node_url(source.identifier)}/posts"
        params: dict[str, Any] = {
            "fields": "id,message,created_time",
            "since": int(since.timestamp()),
            "until": int(until.timestamp()),
            "limit": self._page_size,
        }
        posts: list[ProviderPost] = []
        pages = 0
        while url and pages < self._max_pages:
            body = self._get(url, params, "fetch_posts")
            pages += 1
            for item in body.get("data") or []:
                if not isinstance(item, dict):
                    continue
                posts.append(
                    ProviderPost(
                        external_post_id=str(item["id"]) if item.get("id") else None,
                        posted_at=_parse_created_time(item.get("created_time")),
                        text=item.get("message"),
                    )
                )
            url, params = self._next_page(body)

        if url:
            logger.warning(
                "Stopped paginating at META_MAX_PAGES; older posts in the window were not fetched",
                extra={"source_identifier": source.identifier, "max_pages": self._max_pages},
            )
        return posts

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # -- internals --------------------------------------------------------
    def _unsupported_message(self, source_type: str) -> str:
        if source_type == "group":
            return GROUPS_NOT_SUPPORTED_MESSAGE
        return f"Source type {source_type!r} is not supported by the Meta Graph API provider."

    def _node_url(self, identifier: str) -> str:
        return f"{self._base_url}/{quote(identifier, safe='')}"

    def _auth_params(self) -> dict[str, str]:
        params = {"access_token": self._token}
        if self._app_secret:
            params["appsecret_proof"] = hmac.new(
                self._app_secret.encode(), self._token.encode(), hashlib.sha256
            ).hexdigest()
        return params

    def _next_page(self, body: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        next_url = (body.get("paging") or {}).get("next")
        if not next_url:
            return None, {}
        parsed = httpx.URL(next_url)
        if parsed.host != self._host:
            # Never send the access token to a host other than the Graph API.
            logger.warning(
                "Ignoring pagination URL on unexpected host", extra={"host": parsed.host}
            )
            return None, {}
        params = {
            k: v for k, v in parsed.params.items() if k not in ("access_token", "appsecret_proof")
        }
        return str(parsed.copy_with(query=None)), params

    def _get(self, url: str, params: dict[str, Any], operation: str) -> dict[str, Any]:
        def attempt() -> dict[str, Any]:
            try:
                response = self._client.get(url, params={**params, **self._auth_params()})
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_UNAVAILABLE, "Request to Meta Graph API timed out."
                ) from exc
            except httpx.TransportError as exc:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_UNAVAILABLE,
                    f"Network error contacting Meta Graph API ({type(exc).__name__}).",
                ) from exc
            return self._parse_response(response)

        return call_with_retry(attempt, self._retry, sleep=self._sleep, operation=operation)

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.is_success and isinstance(body, dict) and "error" not in body:
            return body
        error = body.get("error") if isinstance(body, dict) else None
        raise map_graph_error(response.status_code, error if isinstance(error, dict) else {})


def map_graph_error(status_code: int, error: dict[str, Any]) -> ProviderError:
    """Translate a Graph API error payload into a structured :class:`ProviderError`."""
    code = error.get("code")
    subcode = error.get("error_subcode")
    meta_message = str(error.get("message") or f"HTTP {status_code}")
    details = {
        "http_status": status_code,
        "meta_code": code,
        "meta_subcode": subcode,
        "fbtrace_id": error.get("fbtrace_id"),
    }

    if code in _TOKEN_CODES or status_code == 401:
        return ProviderError(
            ProviderErrorCode.TOKEN_EXPIRED,
            f"Access token is expired or invalid: {meta_message}",
            details=details,
        )
    if code in _RATE_LIMIT_CODES or status_code == 429:
        return ProviderError(
            ProviderErrorCode.RATE_LIMITED, f"Meta API rate limit: {meta_message}", details=details
        )
    if code == 10 or (isinstance(code, int) and 200 <= code <= 299) or status_code == 403:
        return ProviderError(
            ProviderErrorCode.PERMISSION_DENIED,
            f"Permission denied (check token permissions / app review): {meta_message}",
            details=details,
        )
    if code == 803 or (code == 100 and subcode == 33) or status_code == 404:
        return ProviderError(
            ProviderErrorCode.INVALID_SOURCE,
            f"Source not found or not accessible: {meta_message}",
            details=details,
        )
    if code in _TRANSIENT_CODES or error.get("is_transient") or status_code >= 500:
        return ProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
            f"Meta API temporarily unavailable: {meta_message}",
            details=details,
        )
    return ProviderError(ProviderErrorCode.PROVIDER_ERROR, meta_message, details=details)
