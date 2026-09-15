from __future__ import annotations

from app.core.config import ProviderName, Settings
from app.providers.base import FacebookDataProvider


def build_provider(settings: Settings) -> FacebookDataProvider:
    """Create the provider selected by ``DATA_PROVIDER`` (validates configuration first)."""
    settings.validate_for_provider()
    if settings.data_provider is ProviderName.META:
        from app.providers.meta_graph import MetaGraphAPIProvider

        return MetaGraphAPIProvider(settings)

    from app.providers.mock import MockFacebookProvider

    return MockFacebookProvider()
