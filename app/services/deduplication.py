"""Application-level deduplication.

Key: ``(source_id, external_post_id)``. The database enforces the same key with
a unique constraint as a final guard. Text is never used as an identity.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Post

_CHUNK = 500


@dataclass(frozen=True, slots=True)
class CandidatePost:
    external_post_id: str
    posted_at: datetime
    text: str
    raw_text: str | None = None
    url: str | None = None
    locations: str | None = None
    hazards: str | None = None


def dedupe_batch(posts: Iterable[CandidatePost]) -> tuple[list[CandidatePost], int]:
    """Drop repeated IDs within one provider response. Returns ``(unique, duplicates)``."""
    seen: set[str] = set()
    unique: list[CandidatePost] = []
    duplicates = 0
    for post in posts:
        if post.external_post_id in seen:
            duplicates += 1
            continue
        seen.add(post.external_post_id)
        unique.append(post)
    return unique, duplicates


def existing_post_ids(session: Session, source_id: int, external_ids: Sequence[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(external_ids), _CHUNK):
        chunk = external_ids[i : i + _CHUNK]
        rows = session.scalars(
            select(Post.external_post_id).where(
                Post.source_id == source_id, Post.external_post_id.in_(chunk)
            )
        )
        found.update(rows)
    return found


def filter_new_posts(
    session: Session, source_id: int, posts: Sequence[CandidatePost]
) -> tuple[list[CandidatePost], int]:
    """Remove posts already stored for this source. Returns ``(new, already_stored)``."""
    existing = existing_post_ids(session, source_id, [p.external_post_id for p in posts])
    new = [p for p in posts if p.external_post_id not in existing]
    return new, len(posts) - len(new)
