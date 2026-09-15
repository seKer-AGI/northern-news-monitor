from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy import func, select

from app.api.dependencies import (
    AppSettings,
    DbSession,
    get_clock,
    get_notifier,
    get_provider,
    get_session_factory_dep,
    require_api_key,
)
from app.api.schemas import (
    CollectionErrorOut,
    CollectionRunDetailOut,
    CollectionRunOut,
    CollectionRunRequest,
    CollectionRunSummaryOut,
    Paginated,
    SourceResultOut,
)
from app.core.exceptions import NotFoundError
from app.db.models import CollectionError, CollectionRun, RunStatus
from app.providers.base import FacebookDataProvider
from app.services.collection import CollectionService
from app.services.notifications import NotificationProvider

router = APIRouter(
    prefix="/api/v1/collection", tags=["collection"], dependencies=[Depends(require_api_key)]
)


@router.post(
    "/run",
    response_model=CollectionRunOut,
    summary="Run collection now (synchronous)",
    responses={
        409: {"description": "A collection run is already in progress"},
        502: {"description": "Run completed but every source failed"},
    },
)
def run_collection(
    response: Response,
    settings: AppSettings,
    provider: Annotated[FacebookDataProvider, Depends(get_provider)],
    notifier: Annotated[NotificationProvider, Depends(get_notifier)],
    factory=Depends(get_session_factory_dep),
    clock=Depends(get_clock),
    payload: Annotated[CollectionRunRequest | None, Body()] = None,
) -> CollectionRunOut:
    """Collects new posts from every active source.

    Returns **200** for ``success`` and ``partial_success`` (inspect ``status``),
    **502** when the run failed, **409** if another run is in progress.
    """
    service = CollectionService(factory, provider, settings, notifier=notifier, clock=clock)
    result = service.run(payload.source_ids if payload else None)
    if result.status == RunStatus.FAILED:
        response.status_code = 502
    return CollectionRunOut(
        id=result.run_id,
        status=result.status,
        provider=result.provider,
        started_at=result.started_at,
        completed_at=result.completed_at,
        sources_processed=result.sources_processed,
        posts_found=result.posts_found,
        posts_saved=result.posts_saved,
        posts_skipped=result.posts_skipped,
        error_count=result.error_count,
        error_message=result.error_message,
        sources=[SourceResultOut(**asdict(s)) for s in result.sources],
    )


@router.get("/runs", response_model=Paginated[CollectionRunSummaryOut])
def list_runs(
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
    status: Annotated[RunStatus | None, Query()] = None,
) -> Paginated[CollectionRunSummaryOut]:
    count_stmt = select(func.count(CollectionRun.id))
    stmt = select(CollectionRun).order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
    if status is not None:
        count_stmt = count_stmt.where(CollectionRun.status == status.value)
        stmt = stmt.where(CollectionRun.status == status.value)
    total = db.scalar(count_stmt) or 0
    runs = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    items = [CollectionRunSummaryOut.model_validate(r) for r in runs]
    return Paginated[CollectionRunSummaryOut].build(items, total, page, page_size)


@router.get("/runs/{run_id}", response_model=CollectionRunDetailOut)
def get_run(run_id: int, db: DbSession) -> CollectionRunDetailOut:
    run = db.get(CollectionRun, run_id)
    if run is None:
        raise NotFoundError(f"Collection run {run_id} not found.")
    errors = db.scalars(
        select(CollectionError).where(CollectionError.run_id == run_id).order_by(CollectionError.id)
    ).all()
    return CollectionRunDetailOut(
        **CollectionRunSummaryOut.model_validate(run).model_dump(),
        errors=[CollectionErrorOut.model_validate(e) for e in errors],
    )
