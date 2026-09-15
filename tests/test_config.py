import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.providers.factory import build_provider
from app.providers.meta_graph import MetaGraphAPIProvider
from app.providers.mock import MockFacebookProvider


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_mock_provider_needs_no_meta_credentials():
    settings = _settings(data_provider="mock")
    settings.validate_for_provider()
    assert isinstance(build_provider(settings), MockFacebookProvider)


def test_meta_provider_reports_all_missing_variables():
    settings = _settings(data_provider="meta")
    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_for_provider()
    assert exc_info.value.details["missing"] == ["META_ACCESS_TOKEN", "META_API_VERSION"]
    assert "META_ACCESS_TOKEN" in exc_info.value.message


def test_build_provider_refuses_incomplete_meta_config():
    with pytest.raises(ConfigurationError):
        build_provider(_settings(data_provider="meta", meta_access_token="abc"))


def test_meta_provider_built_when_configured():
    settings = _settings(data_provider="meta", meta_access_token="tok", meta_api_version="v25.0")
    provider = build_provider(settings)
    try:
        assert isinstance(provider, MetaGraphAPIProvider)
    finally:
        provider.close()


def test_blank_env_values_count_as_missing(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "meta")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("META_API_VERSION", "")
    with pytest.raises(ConfigurationError):
        Settings(_env_file=None).validate_for_provider()


def test_invalid_api_version_rejected():
    with pytest.raises(ValidationError):
        _settings(meta_api_version="25")


def test_missing_internal_api_key_reported():
    with pytest.raises(ConfigurationError):
        _settings().validate_for_api()


def test_secrets_are_masked_in_repr():
    settings = _settings(meta_access_token="super-secret-token", internal_api_key="k" * 20)
    assert "super-secret-token" not in repr(settings)
    assert "super-secret-token" not in str(settings.model_dump())
    assert "super-secret-token" in settings.secret_values()


def test_cors_origins_parsing():
    assert _settings(cors_allowed_origins=" http://a , ,http://b").cors_origins == [
        "http://a",
        "http://b",
    ]
