"""Internal API-key authentication (``Authorization: Bearer <INTERNAL_API_KEY>``)."""

from __future__ import annotations

import hmac

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConfigurationError


def verify_bearer_token(authorization: str | None, settings: Settings) -> None:
    """Validate the Authorization header. Fails closed if no key is configured."""
    if settings.internal_api_key is None:
        raise ConfigurationError(
            "INTERNAL_API_KEY is not configured; protected endpoints are disabled."
        )
    if not authorization:
        raise AuthenticationError("Missing Authorization header.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Authorization header must use the Bearer scheme.")
    expected = settings.internal_api_key.get_secret_value()
    if not hmac.compare_digest(token.strip().encode(), expected.encode()):
        raise AuthenticationError("Invalid API key.")
