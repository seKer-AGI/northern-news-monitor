from __future__ import annotations

from app.core.config import ProviderName, Settings
from app.providers.base import DataProvider
from app.providers.retry import RetryPolicy


def build_facebook_provider(settings: Settings) -> DataProvider:
    """Provider for ``page``/``group`` sources, selected by ``DATA_PROVIDER``."""
    if settings.data_provider is ProviderName.META:
        from app.providers.meta_graph import MetaGraphAPIProvider

        return MetaGraphAPIProvider(settings)

    from app.providers.mock import MockFacebookProvider

    return MockFacebookProvider()


def build_news_providers(settings: Settings) -> dict[str, DataProvider]:
    """Providers for public news feeds and weather forecasts (no credentials)."""
    from app.providers.advisory_page import AdvisoryPageProvider
    from app.providers.feeds import FeedProvider
    from app.providers.http_fetch import HttpFetcher
    from app.providers.weather import OpenMeteoProvider, WeatherThresholds

    def fetcher() -> HttpFetcher:
        return HttpFetcher(
            user_agent=settings.news_user_agent,
            timeout=settings.http_timeout_seconds,
            retry=RetryPolicy(
                max_retries=settings.provider_max_retries,
                base_delay=settings.provider_backoff_base_seconds,
                max_delay=settings.provider_backoff_max_seconds,
            ),
            max_bytes=settings.news_max_response_bytes,
        )

    feeds = FeedProvider(fetcher(), summary_chars=settings.news_summary_chars)
    weather = OpenMeteoProvider(
        fetcher(),
        WeatherThresholds(
            snowfall_cm=settings.weather_snowfall_cm,
            precipitation_mm=settings.weather_precipitation_mm,
            wind_gust_kmh=settings.weather_wind_gust_kmh,
            forecast_days=settings.weather_forecast_days,
        ),
    )
    advisories = AdvisoryPageProvider(fetcher(), user_agent=settings.news_user_agent)
    return {
        "rss": feeds,
        "google_news": feeds,
        "weather": weather,
        "advisory_page": advisories,
    }


def build_provider(settings: Settings) -> DataProvider:
    """Build the provider for all source types (validates configuration first)."""
    settings.validate_for_provider()
    facebook = build_facebook_provider(settings)
    if not settings.news_enabled:
        return facebook

    from app.providers.routing import RoutingProvider

    return RoutingProvider({"page": facebook, "group": facebook, **build_news_providers(settings)})
