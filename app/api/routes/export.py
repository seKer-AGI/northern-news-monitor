from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.dependencies import (
    AppSettings,
    DbSession,
    Filters,
    get_clock,
    get_session_factory_dep,
    require_api_key,
)
from app.core.time import utcnow
from app.services.export import (
    NEWS_EXPORT_COLUMNS,
    csv_chunks,
    iter_export_rows,
    iter_news_rows,
)

router = APIRouter(
    prefix="/api/v1/export", tags=["export"], dependencies=[Depends(require_api_key)]
)


def _filename(prefix: str, ext: str) -> str:
    return f"{prefix}-{utcnow().strftime('%Y%m%dT%H%M%SZ')}.{ext}"


@router.get("/csv", summary="Export posts as CSV (source_name, source_type, posted_at, text)")
def export_csv(settings: AppSettings, filters: Filters, factory=Depends(get_session_factory_dep)):
    def generate() -> Iterator[str]:
        # Own session: the stream outlives the request dependency scope.
        with factory() as session:
            yield from csv_chunks(
                iter_export_rows(session, filters), escape_formulas=settings.csv_escape_formulas
            )

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{_filename("facebook-posts", "csv")}"'
        },
    )


@router.get("/json", summary="Export posts as JSON (source_name, source_type, posted_at, text)")
def export_json(db: DbSession, filters: Filters) -> JSONResponse:
    rows = list(iter_export_rows(db, filters))
    return JSONResponse(
        rows,
        headers={
            "Content-Disposition": f'attachment; filename="{_filename("facebook-posts", "json")}"'
        },
    )


@router.get(
    "/news-csv",
    summary="Northern-areas weather/hazard news as CSV (newest first, duplicates collapsed)",
)
def export_news_csv(
    settings: AppSettings,
    filters: Filters,
    factory=Depends(get_session_factory_dep),
    clock=Depends(get_clock),
    since_hours: Annotated[
        int | None, Query(ge=1, le=24 * 90, description="Only items collected in the last N hours")
    ] = None,
    dedupe: Annotated[
        bool, Query(description="Collapse the same story from several outlets")
    ] = True,
):
    collected_since = clock() - timedelta(hours=since_hours) if since_hours else None

    def generate() -> Iterator[str]:
        with factory() as session:
            yield from csv_chunks(
                iter_news_rows(session, filters, dedupe=dedupe, collected_since=collected_since),
                escape_formulas=settings.csv_escape_formulas,
                fieldnames=NEWS_EXPORT_COLUMNS,
            )

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_filename("northern-weather-news", "csv")}"'
            )
        },
    )
