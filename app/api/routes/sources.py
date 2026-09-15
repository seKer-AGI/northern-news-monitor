from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import DbSession, get_provider, require_api_key
from app.api.schemas import SourceCreate, SourceOut, SourceUpdate, SourceValidationOut
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Source, SourceType
from app.providers.base import FacebookDataProvider, SourceRef

router = APIRouter(
    prefix="/api/v1/sources", tags=["sources"], dependencies=[Depends(require_api_key)]
)


def _get_or_404(db, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise NotFoundError(f"Source {source_id} not found.")
    return source


@router.get("", response_model=list[SourceOut])
def list_sources(
    db: DbSession,
    active: Annotated[bool | None, Query()] = None,
    source_type: Annotated[SourceType | None, Query()] = None,
) -> list[Source]:
    stmt = select(Source).order_by(Source.id)
    if active is not None:
        stmt = stmt.where(Source.active.is_(active))
    if source_type is not None:
        stmt = stmt.where(Source.source_type == source_type.value)
    return list(db.scalars(stmt))


@router.get("/{source_id}", response_model=SourceOut)
def get_source(source_id: int, db: DbSession) -> Source:
    return _get_or_404(db, source_id)


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, db: DbSession) -> Source:
    duplicate = db.scalar(
        select(Source.id).where(
            Source.source_type == payload.source_type.value,
            Source.source_identifier == payload.source_identifier,
        )
    )
    if duplicate is not None:
        raise ConflictError(
            "A source with this type and identifier already exists.",
            details={"source_id": duplicate},
        )
    source = Source(**{**payload.model_dump(), "source_type": payload.source_type.value})
    db.add(source)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A source with this type and identifier already exists.") from exc
    return source


@router.patch("/{source_id}", response_model=SourceOut)
def update_source(source_id: int, payload: SourceUpdate, db: DbSession) -> Source:
    source = _get_or_404(db, source_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in ("source_name", "active") and value is None:
            continue
        setattr(source, field, value)
    db.commit()
    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: int, db: DbSession) -> Response:
    """Delete a source **and its collected posts**. Use PATCH ``active=false`` to pause instead."""
    source = _get_or_404(db, source_id)
    db.delete(source)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/validate", response_model=SourceValidationOut)
def validate_source(
    source_id: int,
    db: DbSession,
    provider: Annotated[FacebookDataProvider, Depends(get_provider)],
) -> SourceValidationOut:
    source = _get_or_404(db, source_id)
    result = provider.validate_source(
        SourceRef(
            source.source_type, source.source_identifier, source.source_name, source.source_url
        )
    )
    return SourceValidationOut(
        source_id=source.id,
        ok=result.ok,
        resolved_name=result.resolved_name,
        error_code=str(result.error_code) if result.error_code else None,
        message=result.message,
    )
