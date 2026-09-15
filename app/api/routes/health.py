from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text

from app import __version__
from app.api.dependencies import AppSettings, get_provider, get_session_factory_dep, require_api_key
from app.api.schemas import HealthOut, ProviderHealthOut
from app.providers.base import FacebookDataProvider

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut, summary="Liveness and database connectivity")
def health(
    response: Response,
    settings: AppSettings,
    factory=Depends(get_session_factory_dep),
) -> HealthOut:
    database = "ok"
    try:
        with factory() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Database health check failed", extra={"error": type(exc).__name__})
        database = "unavailable"
        response.status_code = 503
    return HealthOut(
        status="ok" if database == "ok" else "degraded",
        version=__version__,
        database=database,
        data_provider=settings.data_provider.value,
    )


@router.get(
    "/api/v1/provider/health",
    response_model=ProviderHealthOut,
    dependencies=[Depends(require_api_key)],
    summary="Check provider credentials/connectivity (no source data is read)",
)
def provider_health(
    response: Response, provider: Annotated[FacebookDataProvider, Depends(get_provider)]
) -> ProviderHealthOut:
    result = provider.health_check()
    if not result.ok:
        response.status_code = 502
    return ProviderHealthOut(
        ok=result.ok, provider=result.provider, message=result.message, details=result.details
    )
