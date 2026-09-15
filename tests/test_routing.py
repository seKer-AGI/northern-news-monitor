from datetime import UTC, datetime

import pytest

from app.providers.base import (
    FacebookDataProvider,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
    ProviderPost,
    SourceRef,
    SourceValidation,
)
from app.providers.mock import MockFacebookProvider
from app.providers.routing import RoutingProvider

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


class FakeNews(FacebookDataProvider):
    name = "fake_news"
    supported_source_types = frozenset({"rss"})

    def __init__(self):
        self.closed = 0
        self.refs = []

    def fetch_posts(self, source, since, until):
        self.refs.append(source)
        return [ProviderPost("n1", NOW, "news")]

    def validate_source(self, source):
        return SourceValidation(ok=True, resolved_name="Fake")

    def health_check(self):
        return ProviderHealth(ok=False, provider=self.name, message="down")

    def close(self):
        self.closed += 1


def test_routes_by_source_type_and_aggregates():
    news = FakeNews()
    fb = MockFacebookProvider()
    router = RoutingProvider({"page": fb, "group": fb, "rss": news, "google_news": news})

    assert router.name == "mock+fake_news"
    assert router.supported_source_types == {"page", "group", "rss", "google_news"}
    ref = SourceRef("rss", "dawn", "Dawn", "https://x.test")
    assert router.fetch_posts(ref, NOW, NOW)[0].text == "news"
    assert news.refs[0].url == "https://x.test"

    health = router.health_check()
    assert not health.ok
    assert set(health.details) == {"mock", "fake_news"}

    router.close()
    assert news.closed == 1  # shared provider closed once


def test_unsupported_type_is_structured_error():
    router = RoutingProvider({"page": MockFacebookProvider()})
    validation = router.validate_source(SourceRef("weather", "murree"))
    assert not validation.ok and validation.error_code == ProviderErrorCode.SOURCE_NOT_SUPPORTED
    with pytest.raises(ProviderError):
        router.fetch_posts(SourceRef("weather", "murree"), NOW, NOW)
