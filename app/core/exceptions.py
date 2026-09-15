"""Application exception hierarchy.

Every error carries a stable machine-readable ``code`` so that API clients
(and n8n workflows) can branch on it without parsing messages.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all expected application errors."""

    code: str = "APP_ERROR"
    status_code: int = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(AppError):
    code = "CONFIGURATION_ERROR"
    status_code = 503


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = 409


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422


class AuthenticationError(AppError):
    code = "UNAUTHORIZED"
    status_code = 401


class CollectionAlreadyRunningError(ConflictError):
    code = "COLLECTION_ALREADY_RUNNING"
