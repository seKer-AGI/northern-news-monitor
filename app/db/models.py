"""SQLAlchemy ORM models.

Data minimization: posts hold only text, identifiers and timestamps. No media,
comments, reactions, author profiles or other personal data are modelled.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.time import utcnow
from app.db.types import UTCDateTime

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class SourceType(StrEnum):
    PAGE = "page"
    GROUP = "group"
    RSS = "rss"
    GOOGLE_NEWS = "google_news"
    WEATHER = "weather"
    ADVISORY_PAGE = "advisory_page"


FACEBOOK_SOURCE_TYPES = frozenset({SourceType.PAGE.value, SourceType.GROUP.value})
NEWS_SOURCE_TYPES = frozenset(
    {
        SourceType.RSS.value,
        SourceType.GOOGLE_NEWS.value,
        SourceType.WEATHER.value,
        SourceType.ADVISORY_PAGE.value,
    }
)
# Types whose source_url is the endpoint to read.
URL_SOURCE_TYPES = frozenset(
    {SourceType.RSS.value, SourceType.GOOGLE_NEWS.value, SourceType.ADVISORY_PAGE.value}
)
# Official agency advisories are relevant by definition (no keyword filter).
OFFICIAL_SOURCE_TYPES = frozenset({SourceType.ADVISORY_PAGE.value})


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("source_type", "source_identifier", name="uq_sources_type_identifier"),
        CheckConstraint(
            "source_type IN ('page', 'group', 'rss', 'google_news', 'weather', 'advisory_page')",
            name="source_type_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    # Per-source incremental watermark: the upper bound of the last window that
    # was fully processed for this source. See docs/architecture.md.
    last_collected_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("source_id", "external_post_id", name="uq_posts_source_external_post"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_post_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # News/weather sources only: article link and matched keywords.
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    locations: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hazards: Mapped[str | None] = mapped_column(String(500), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'partial_success', 'failed')", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    sources_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    posts_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    posts_saved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    posts_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class CollectionError(Base):
    __tablename__ = "collection_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("collection_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
