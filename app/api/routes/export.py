from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.dependencies import (
    AppSettings,
    DbSession,
    Filters,
    get_session_factory_dep,
    require_api_key,
)
from app.core.time import utcnow
from app.services.export import csv_chunks, iter_export_rows

router = APIRouter(
    prefix="/api/v1/export", tags=["export"], dependencies=[Depends(require_api_key)]
)


def _filename(ext: str) -> str:
    return f"facebook-posts-{utcnow().strftime('%Y%m%dT%H%M%SZ')}.{ext}"


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
        headers={"Content-Disposition": f'attachment; filename="{_filename("csv")}"'},
    )


@router.get("/json", summary="Export posts as JSON (source_name, source_type, posted_at, text)")
def export_json(db: DbSession, filters: Filters) -> JSONResponse:
    rows = list(iter_export_rows(db, filters))
    return JSONResponse(
        rows, headers={"Content-Disposition": f'attachment; filename="{_filename("json")}"'}
    )
