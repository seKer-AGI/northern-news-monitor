"""CSV / JSON export.

* Facebook export: only ``source_name, source_type, posted_at, text``.
* News export: ``posted_at_pkt, source_name, source_type, locations, hazards,
  text, url`` for news/weather sources, newest first, with the same story from
  several outlets collapsed to one row.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import isoformat_z
from app.db.models import NEWS_SOURCE_TYPES, Post
from app.services.posts import PostFilters, apply_filters

EXPORT_COLUMNS = ("source_name", "source_type", "posted_at", "text")
NEWS_EXPORT_COLUMNS = (
    "posted_at_pkt",
    "source_name",
    "source_type",
    "locations",
    "hazards",
    "text",
    "url",
)
PKT = timezone(timedelta(hours=5), "PKT")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
# " - tribune.com.pk", " | Dawn" style publisher suffixes on headlines
_PUBLISHER_SUFFIX_RE = re.compile(r"\s+[-–|]\s+[^-–|]{2,60}$")
_NON_WORD_RE = re.compile(r"\W+")


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


def news_story_key(text: str) -> str:
    """Normalised headline used to collapse the same story from several outlets."""
    headline = _PUBLISHER_SUFFIX_RE.sub("", text.split("\n", 1)[0])
    return _NON_WORD_RE.sub(" ", headline).casefold().strip()


def iter_news_rows(
    session: Session,
    filters: PostFilters,
    *,
    dedupe: bool = True,
    collected_since: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    """News rows, newest first. ``collected_since`` selects items newly collected
    after that moment (what a daily report wants), independent of publish time."""
    stmt = (
        apply_filters(
            select(
                Post.posted_at,
                Post.source_name,
                Post.source_type,
                Post.locations,
                Post.hazards,
                Post.text,
                Post.url,
            ),
            filters,
        )
        .where(Post.source_type.in_(sorted(NEWS_SOURCE_TYPES)))
        .order_by(Post.posted_at.desc(), Post.id.desc())
        .execution_options(yield_per=500)
    )
    if collected_since is not None:
        stmt = stmt.where(Post.collected_at >= collected_since)
    seen: set[str] = set()
    for posted_at, source_name, source_type, locations, hazards, text, url in session.execute(stmt):
        if dedupe:
            key = news_story_key(text)
            if key in seen:
                continue
            seen.add(key)
        yield {
            "posted_at_pkt": posted_at.astimezone(PKT).strftime("%Y-%m-%d %H:%M"),
            "source_name": source_name,
            "source_type": source_type,
            "locations": locations or "",
            "hazards": hazards or "",
            "text": text,
            "url": url or "",
        }


def _escape_formula(value: str) -> str:
    """Neutralize spreadsheet formula injection (CSV opened in Excel/Sheets)."""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def csv_chunks(
    rows: Iterator[dict[str, Any]],
    *,
    escape_formulas: bool = True,
    fieldnames: Sequence[str] = EXPORT_COLUMNS,
) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames), lineterminator="\n")
    buffer.write("﻿")  # BOM so Excel detects UTF-8 (Urdu, emoji, ...)
    writer.writeheader()
    for row in rows:
        if escape_formulas:
            row = {
                k: _escape_formula(v) if isinstance(v, str) and k != "url" else v
                for k, v in row.items()
            }
        writer.writerow(row)
        if buffer.tell() > 64_000:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()
    yield buffer.getvalue()


def to_csv(
    rows: Iterator[dict[str, Any]],
    *,
    escape_formulas: bool = True,
    fieldnames: Sequence[str] = EXPORT_COLUMNS,
) -> str:
    return "".join(csv_chunks(rows, escape_formulas=escape_formulas, fieldnames=fieldnames))
