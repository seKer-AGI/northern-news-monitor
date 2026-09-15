"""Routes each source to the provider that handles its ``source_type``."""

from __future__ import annotations

from datetime import datetime

from app.providers.base import (
    FacebookDataProvider,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
    ProviderPost,
    SourceRef,
    SourceValidation,
)


class RoutingProvider(FacebookDataProvider):
    def __init__(self, routes: dict[str, FacebookDataProvider]) -> None:
        self._routes = dict(routes)
        self._unique = list({id(p): p for p in self._routes.values()}.values())
        self.supported_source_types = frozenset(self._routes)
        self.name = "+".join(p.name for p in self._unique)[:50]

    def _route(self, source_type: str) -> FacebookDataProvider:
        provider = self._routes.get(source_type)
        if provider is None:
            raise ProviderError(
                ProviderErrorCode.SOURCE_NOT_SUPPORTED,
                f"No provider configured for source type {source_type!r}.",
            )
        return provider

    def fetch_posts(
        self, source: SourceRef, since: datetime, until: datetime
    ) -> list[ProviderPost]:
        return self._route(source.source_type).fetch_posts(source, since, until)

    def validate_source(self, source: SourceRef) -> SourceValidation:
        try:
            provider = self._route(source.source_type)
        except ProviderError as exc:
            return SourceValidation(ok=False, error_code=exc.code, message=exc.message)
        return provider.validate_source(source)

    def health_check(self) -> ProviderHealth:
        results = [p.health_check() for p in self._unique]
        return ProviderHealth(
            ok=all(r.ok for r in results),
            provider=self.name,
            message="; ".join(f"{r.provider}: {r.message}" for r in results),
            details={r.provider: {"ok": r.ok, "message": r.message} for r in results},
        )

    def close(self) -> None:
        for provider in self._unique:
            provider.close()
