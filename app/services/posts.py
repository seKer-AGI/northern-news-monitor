"""Post querying shared by the posts API and exports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import Post


@dataclass(frozen=True, slots=True)
class PostFilters:
    source_id: int | None = None
    source_type: str | None = None
    start_date: datetime | None = None  # inclusive
    end_date: datetime | None = None  # inclusive


def apply_filters(stmt: Select, filters: PostFilters) -> Select:
    if filters.source_id is not None:
        stmt = stmt.where(Post.source_id == filters.source_id)
    if filters.source_type is not None:
        stmt = stmt.where(Post.source_type == filters.source_type)
    if filters.start_date is not None:
        stmt = stmt.where(Post.posted_at >= filters.start_date)
    if filters.end_date is not None:
        stmt = stmt.where(Post.posted_at <= filters.end_date)
    return stmt


def list_posts(
    session: Session, filters: PostFilters, *, page: int, page_size: int
) -> tuple[list[Post], int]:
    total = session.scalar(apply_filters(select(func.count(Post.id)), filters)) or 0
    stmt = (
        apply_filters(select(Post), filters)
        .order_by(Post.posted_at.desc(), Post.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(session.scalars(stmt)), total
