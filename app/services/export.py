"""CSV / JSON export. Only ``source_name, source_type, posted_at, text`` are exported."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import isoformat_z
from app.db.models import Post
from app.services.posts import PostFilters, apply_filters

EXPORT_COLUMNS = ("source_name", "source_type", "posted_at", "text")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def iter_export_rows(session: Session, filters: PostFilters) -> Iterator[dict[str, Any]]:
    stmt = (
        apply_filters(
            select(Post.source_name, Post.source_type, Post.posted_at, Post.text), filters
        )
        .order_by(Post.posted_at.asc(), Post.id.asc())
        .execution_options(yield_per=500)
    )
    for source_name, source_type, posted_at, text in session.execute(stmt):
        yield {
            "source_name": source_name,
            "source_type": source_type,
            "posted_at": isoformat_z(posted_at),
            "text": text,
        }


def _escape_formula(value: str) -> str:
    """Neutralize spreadsheet formula injection (CSV opened in Excel/Sheets)."""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def csv_chunks(rows: Iterator[dict[str, Any]], *, escape_formulas: bool = True) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
    buffer.write("﻿")  # BOM so Excel detects UTF-8 (Urdu, emoji, ...)
    writer.writeheader()
    for row in rows:
        if escape_formulas:
            row = {k: _escape_formula(v) if isinstance(v, str) else v for k, v in row.items()}
        writer.writerow(row)
        if buffer.tell() > 64_000:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()
    yield buffer.getvalue()


def to_csv(rows: Iterator[dict[str, Any]], *, escape_formulas: bool = True) -> str:
    return "".join(csv_chunks(rows, escape_formulas=escape_formulas))
