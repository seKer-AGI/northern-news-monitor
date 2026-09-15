from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.providers.base import ProviderError, ProviderErrorCode, SourceRef
from app.providers.http_fetch import HttpFetcher
from app.providers.retry import RetryPolicy
from app.providers.weather import NORTHERN_LOCATIONS, OpenMeteoProvider, WeatherThresholds
from app.services.relevance import match_relevance

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
DAILY = {
    "time": ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"],
    "snowfall_sum": [0.0, 12.4, 0.0, None],
    "precipitation_sum": [3.0, 30.0, 1.0, None],
    "weather_code": [3, 73, 95, None],
    "wind_gusts_10m_max": [20.0, 45.0, 72.0, None],
}


def _provider(handler=None):
    handler = handler or (lambda r: httpx.Response(200, json={"daily": DAILY}))
    fetcher = HttpFetcher(
        user_agent="test",
        timeout=5,
        retry=RetryPolicy(max_retries=0, base_delay=0, max_delay=0),
        max_bytes=100_000,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return OpenMeteoProvider(fetcher, WeatherThresholds())


def test_alerts_only_for_days_over_thresholds():
    provider = _provider()
    posts = provider.alerts_from_daily(NORTHERN_LOCATIONS["murree"], DAILY, posted_at=NOW)

    assert [p.external_post_id for p in posts] == [
        "murree:2026-09-16:snow+rain",
        "murree:2026-09-17:wind+thunderstorm",
    ]
    snow = posts[0]
    assert "Murree (مری)" in snow.text
    assert "heavy snowfall about 12 cm" in snow.text
    assert "Wed 16 Sep 2026" in snow.text
    assert snow.posted_at == NOW
    assert snow.url.startswith("https://open-meteo.com/")


def test_alert_text_passes_relevance_filter():
    provider = _provider()
    for post in provider.alerts_from_daily(NORTHERN_LOCATIONS["babusar-top"], DAILY, posted_at=NOW):
        assert match_relevance(post.text).relevant


def test_fetch_posts_requests_forecast_for_location():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        seen["host"] = request.url.host
        return httpx.Response(200, json={"daily": DAILY})

    posts = _provider(handler).fetch_posts(SourceRef("weather", "skardu", "Skardu"), NOW, NOW)
    assert len(posts) == 2
    assert seen["host"] == "api.open-meteo.com"
    assert seen["latitude"] == "35.297" and seen["longitude"] == "75.633"
    assert seen["timezone"] == "Asia/Karachi"
    assert "snowfall_sum" in seen["daily"]


def test_unknown_location_is_invalid():
    provider = _provider()
    result = provider.validate_source(SourceRef("weather", "karachi", "Karachi"))
    assert not result.ok and result.error_code == ProviderErrorCode.INVALID_SOURCE
    assert "murree" in result.message


def test_unexpected_response_is_provider_error():
    provider = _provider(lambda r: httpx.Response(200, content=json.dumps({"oops": 1}).encode()))
    with pytest.raises(ProviderError) as exc:
        provider.fetch_posts(SourceRef("weather", "gilgit", "Gilgit"), NOW, NOW)
    assert exc.value.code == ProviderErrorCode.PROVIDER_ERROR


def test_all_seed_locations_are_in_the_north():
    for loc in NORTHERN_LOCATIONS.values():
        assert 33.5 <= loc.latitude <= 37.1, loc
        assert 71.0 <= loc.longitude <= 77.0, loc
