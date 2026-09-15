from datetime import timedelta

import pytest

from app.providers.base import ProviderError, ProviderErrorCode, SourceRef
from app.providers.mock import MOCK_TEXTS, MockFacebookProvider


def _window(clock):
    return clock.now - timedelta(hours=24), clock.now


def test_generates_realistic_posts_with_stable_ids(clock):
    provider = MockFacebookProvider(clock=clock)
    ref = SourceRef("group", "ai-jobs", "AI Jobs")
    first = provider.fetch_posts(ref, *_window(clock))
    second = provider.fetch_posts(ref, *_window(clock))

    assert first == second
    texts = {p.text for p in first if p.text}
    assert texts <= set(MOCK_TEXTS)
    assert all(p.posted_at <= clock.now for p in first)


def test_includes_out_of_window_duplicate_and_media_only_posts(clock):
    provider = MockFacebookProvider(clock=clock)
    posts = provider.fetch_posts(SourceRef("page", "demo"), *_window(clock))

    ids = [p.external_post_id for p in posts]
    assert len(ids) != len(set(ids)), "expected an in-batch duplicate"
    assert any(p.posted_at < clock.now - timedelta(hours=24) for p in posts)
    assert any(p.text is None for p in posts)


@pytest.mark.parametrize(
    ("identifier", "code"),
    [
        ("mock-permission-denied", ProviderErrorCode.PERMISSION_DENIED),
        ("mock-not-supported", ProviderErrorCode.SOURCE_NOT_SUPPORTED),
        ("mock-invalid", ProviderErrorCode.INVALID_SOURCE),
        ("mock-token-expired", ProviderErrorCode.TOKEN_EXPIRED),
        ("mock-rate-limited", ProviderErrorCode.RATE_LIMITED),
        ("mock-unavailable", ProviderErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_failure_identifiers_raise_structured_errors(clock, identifier, code):
    provider = MockFacebookProvider(clock=clock)
    with pytest.raises(ProviderError) as exc_info:
        provider.fetch_posts(SourceRef("page", identifier), *_window(clock))
    assert exc_info.value.code == code


def test_validate_source_reports_permanent_failures(clock):
    provider = MockFacebookProvider(clock=clock)
    assert provider.validate_source(SourceRef("page", "ok-page", "OK")).ok
    result = provider.validate_source(SourceRef("page", "mock-permission-denied"))
    assert not result.ok
    assert result.error_code == ProviderErrorCode.PERMISSION_DENIED


def test_no_id_source_returns_posts_without_ids(clock):
    provider = MockFacebookProvider(clock=clock)
    posts = provider.fetch_posts(SourceRef("page", "mock-no-id"), *_window(clock))
    assert posts and all(p.external_post_id is None for p in posts)


def test_health_check(clock):
    assert MockFacebookProvider(clock=clock).health_check().ok
