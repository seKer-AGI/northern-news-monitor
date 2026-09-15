"""Meta Graph provider tests using httpx.MockTransport — no network, no credentials."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import Settings
from app.providers.base import ProviderError, ProviderErrorCode, SourceRef
from app.providers.meta_graph import MetaGraphAPIProvider, map_graph_error

TOKEN = "EAAtest-token"
UNTIL = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
SINCE = UNTIL - timedelta(hours=24)


def _settings(**kwargs) -> Settings:
    base = dict(
        data_provider="meta",
        meta_access_token=TOKEN,
        meta_api_version="v25.0",
        provider_max_retries=2,
        provider_backoff_base_seconds=0,
        provider_backoff_max_seconds=0,
    )
    return Settings(_env_file=None, **(base | kwargs))


def _provider(handler, **settings_kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    provider = MetaGraphAPIProvider(
        _settings(**settings_kwargs), client=client, sleep=sleeps.append
    )
    return provider, sleeps


def _graph_error(status, code, message="err", subcode=None):
    error = {"message": message, "type": "OAuthException", "code": code, "fbtrace_id": "trace"}
    if subcode is not None:
        error["error_subcode"] = subcode
    return httpx.Response(status, json={"error": error})


def test_fetch_posts_requests_documented_fields_and_paginates():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "after" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "1_2",
                            "message": "Hiring a Python developer",
                            "created_time": "2026-09-14T10:30:00+0000",
                        },
                        {"id": "1_3", "created_time": "2026-09-14T09:00:00+0000"},  # photo-only
                    ],
                    "paging": {
                        "next": "https://graph.facebook.com/v25.0/123/posts?access_token=OLD&limit=100&after=CURSOR"
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "1_4", "message": "Older", "created_time": "2026-09-14T01:00:00+0000"}
                ]
            },
        )

    provider, _ = _provider(handler)
    posts = provider.fetch_posts(SourceRef("page", "123"), SINCE, UNTIL)

    assert [p.external_post_id for p in posts] == ["1_2", "1_3", "1_4"]
    assert posts[0].posted_at == datetime(2026, 9, 14, 10, 30, tzinfo=UTC)
    assert posts[0].text == "Hiring a Python developer"
    assert posts[1].text is None

    first = requests[0].url
    assert first.path == "/v25.0/123/posts"
    assert first.params["fields"] == "id,message,created_time"
    assert first.params["since"] == str(int(SINCE.timestamp()))
    assert first.params["until"] == str(int(UNTIL.timestamp()))
    assert first.params["limit"] == "100"
    assert first.params["access_token"] == TOKEN
    # Pagination re-applies our own token rather than trusting the one in `next`.
    assert requests[1].url.params["access_token"] == TOKEN
    assert requests[1].url.params["after"] == "CURSOR"


def test_appsecret_proof_sent_when_secret_configured():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"id": "1", "name": "Page"})

    provider, _ = _provider(handler, meta_app_secret="shh")
    assert provider.health_check().ok
    assert len(seen["appsecret_proof"]) == 64


def test_groups_are_not_supported_and_make_no_request():
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("no HTTP request expected for groups")

    provider, _ = _provider(handler)
    with pytest.raises(ProviderError) as exc_info:
        provider.fetch_posts(SourceRef("group", "999"), SINCE, UNTIL)
    assert exc_info.value.code == ProviderErrorCode.SOURCE_NOT_SUPPORTED
    assert "Groups API" in exc_info.value.message

    validation = provider.validate_source(SourceRef("group", "999"))
    assert not validation.ok
    assert validation.error_code == ProviderErrorCode.SOURCE_NOT_SUPPORTED


def test_pagination_stops_at_max_pages():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": f"p{calls}", "message": "m", "created_time": "2026-09-14T10:00:00+0000"}
                ],
                "paging": {"next": f"https://graph.facebook.com/v25.0/1/posts?after=c{calls}"},
            },
        )

    provider, _ = _provider(handler, meta_max_pages=3)
    assert len(provider.fetch_posts(SourceRef("page", "1"), SINCE, UNTIL)) == 3
    assert calls == 3


def test_token_never_sent_to_foreign_pagination_host():
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(
            200, json={"data": [], "paging": {"next": "https://evil.example/steal?after=x"}}
        )

    provider, _ = _provider(handler)
    provider.fetch_posts(SourceRef("page", "1"), SINCE, UNTIL)
    assert hosts == ["graph.facebook.com"]


def test_transient_errors_retry_then_succeed():
    responses = iter(
        [
            _graph_error(500, 2, "Service temporarily unavailable"),
            _graph_error(400, 4, "Application request limit reached"),
            httpx.Response(200, json={"data": []}),
        ]
    )
    provider, sleeps = _provider(lambda request: next(responses))
    assert provider.fetch_posts(SourceRef("page", "1"), SINCE, UNTIL) == []
    assert len(sleeps) == 2


def test_retries_are_bounded():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return _graph_error(503, 2)

    provider, sleeps = _provider(handler, provider_max_retries=2)
    with pytest.raises(ProviderError) as exc_info:
        provider.fetch_posts(SourceRef("page", "1"), SINCE, UNTIL)
    assert exc_info.value.code == ProviderErrorCode.PROVIDER_UNAVAILABLE
    assert calls == 3
    assert len(sleeps) == 2


def test_permanent_errors_are_not_retried():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return _graph_error(400, 190, "Error validating access token: Session has expired", 463)

    provider, sleeps = _provider(handler)
    with pytest.raises(ProviderError) as exc_info:
        provider.fetch_posts(SourceRef("page", "1"), SINCE, UNTIL)
    assert exc_info.value.code == ProviderErrorCode.TOKEN_EXPIRED
    assert calls == 1 and sleeps == []


def test_timeout_maps_to_provider_unavailable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    provider, sleeps = _provider(handler, provider_max_retries=1)
    with pytest.raises(ProviderError) as exc_info:
        provider.fetch_posts(SourceRef("page", "1"), SINCE, UNTIL)
    assert exc_info.value.code == ProviderErrorCode.PROVIDER_UNAVAILABLE
    assert TOKEN not in exc_info.value.message
    assert len(sleeps) == 1


@pytest.mark.parametrize(
    ("status", "code", "subcode", "expected"),
    [
        (400, 190, None, ProviderErrorCode.TOKEN_EXPIRED),
        (400, 102, None, ProviderErrorCode.TOKEN_EXPIRED),
        (400, 4, None, ProviderErrorCode.RATE_LIMITED),
        (400, 17, None, ProviderErrorCode.RATE_LIMITED),
        (400, 32, None, ProviderErrorCode.RATE_LIMITED),
        (400, 80001, None, ProviderErrorCode.RATE_LIMITED),
        (400, 10, None, ProviderErrorCode.PERMISSION_DENIED),
        (403, 200, None, ProviderErrorCode.PERMISSION_DENIED),
        (400, 100, 33, ProviderErrorCode.INVALID_SOURCE),
        (404, 803, None, ProviderErrorCode.INVALID_SOURCE),
        (500, 1, None, ProviderErrorCode.PROVIDER_UNAVAILABLE),
        (400, 100, None, ProviderErrorCode.PROVIDER_ERROR),
    ],
)
def test_error_mapping(status, code, subcode, expected):
    error = {"code": code, "message": "m"}
    if subcode:
        error["error_subcode"] = subcode
    assert map_graph_error(status, error).code == expected


def test_validate_source_and_health_check_report_errors():
    provider, _ = _provider(lambda request: _graph_error(400, 100, "Object does not exist", 33))
    result = provider.validate_source(SourceRef("page", "nope"))
    assert not result.ok and result.error_code == ProviderErrorCode.INVALID_SOURCE

    provider, _ = _provider(lambda request: _graph_error(400, 190, "Invalid OAuth access token"))
    health = provider.health_check()
    assert not health.ok
    assert TOKEN not in health.message


def test_identifier_is_url_encoded():
    paths = []

    def handler(request):
        paths.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"id": "1", "name": "n"})

    provider, _ = _provider(handler)
    provider.validate_source(SourceRef("page", "a/b?c"))
    assert paths[0].startswith("/v25.0/a%2Fb%3Fc?")


def test_provider_requires_configuration():
    with pytest.raises(ProviderError) as exc_info:
        MetaGraphAPIProvider(Settings(_env_file=None, data_provider="meta"))
    assert exc_info.value.code == ProviderErrorCode.CONFIGURATION_ERROR
