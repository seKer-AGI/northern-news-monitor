"""FastAPI application factory.

Run with: ``uvicorn app.main:create_app --factory`` (or ``python -m app serve``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.middleware import BodySizeLimitMiddleware
from app.api.routes import collection, export, health, posts, sources
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.time import Clock, utcnow
from app.db.session import create_engine_from_url, make_session_factory
from app.providers.base import DataProvider
from app.providers.factory import build_provider

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    provider_factory: Callable[[Settings], DataProvider] | None = None,
    clock: Clock = utcnow,
    setup_logging: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    if setup_logging:
        configure_logging(settings.log_level, settings.log_format, settings.secret_values())

    app = FastAPI(
        title="Northern News Monitor",
        version=__version__,
        description=(
            "Collects the text of new posts from configured Facebook sources through an "
            "authorized data provider. Access depends on Meta's current permissions."
        ),
    )
    app.state.settings = settings
    app.state.session_factory = session_factory or make_session_factory(
        create_engine_from_url(settings.database_url)
    )
    app.state.provider_factory = provider_factory or build_provider
    app.state.clock = clock

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )

    register_exception_handlers(app)
    for module in (health, sources, collection, posts, export):
        app.include_router(module.router)

    if settings.internal_api_key is None:
        logger.warning("INTERNAL_API_KEY is not set: all /api/v1 endpoints will return 503.")
    logger.info(
        "Application configured",
        extra={"data_provider": settings.data_provider.value, "app_env": settings.app_env},
    )
    return app
