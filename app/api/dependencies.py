"""FastAPI dependencies. Everything is resolved from ``app.state`` so tests can inject fakes."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.exceptions import ValidationError
from app.core.security import verify_bearer_token
from app.core.time import Clock, parse_date_param
from app.db.models import SourceType
from app.providers.base import DataProvider
from app.services.notifications import NotificationProvider, build_notifier
from app.services.posts import PostFilters


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_factory_dep(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_db(
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory_dep)],
) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_provider(
    request: Request, settings: Annotated[Settings, Depends(get_app_settings)]
) -> Iterator[DataProvider]:
    provider = request.app.state.provider_factory(settings)
    try:
        yield provider
    finally:
        provider.close()


def get_notifier(settings: Annotated[Settings, Depends(get_app_settings)]) -> NotificationProvider:
    return build_notifier(settings)


def require_api_key(
    settings: Annotated[Settings, Depends(get_app_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    verify_bearer_token(authorization, settings)


def post_filters(
    source_id: Annotated[int | None, Query(ge=1, description="Filter by source ID")] = None,
    source_type: Annotated[SourceType | None, Query(description="page or group")] = None,
    start_date: Annotated[
        str | None, Query(max_length=40, description="ISO 8601 datetime or YYYY-MM-DD (inclusive)")
    ] = None,
    end_date: Annotated[
        str | None,
        Query(max_length=40, description="ISO 8601 datetime or YYYY-MM-DD (inclusive, whole day)"),
    ] = None,
) -> PostFilters:
    try:
        start = parse_date_param(start_date) if start_date else None
        end = parse_date_param(end_date, is_end=True) if end_date else None
    except ValueError as exc:
        raise ValidationError(
            "start_date and end_date must be ISO 8601 datetimes or YYYY-MM-DD dates."
        ) from exc
    if start and end and start > end:
        raise ValidationError("start_date must not be after end_date.")
    return PostFilters(
        source_id=source_id,
        source_type=source_type.value if source_type else None,
        start_date=start,
        end_date=end,
    )


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
Filters = Annotated[PostFilters, Depends(post_filters)]
