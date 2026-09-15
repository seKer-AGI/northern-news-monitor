"""Request / response models. Secrets are never part of any response."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import RunStatus, SourceType

T = TypeVar("T")

IDENTIFIER_PATTERN = r"^[A-Za-z0-9._-]+$"
URL_PATTERN = r"^https?://\S+$"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Paginated(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(cls, items: list[T], total: int, page: int, page_size: int) -> Paginated[T]:
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )


# --- Sources ----------------------------------------------------------------
class SourceCreate(_Input):
    source_type: SourceType
    source_name: str = Field(min_length=1, max_length=255)
    source_identifier: str = Field(
        min_length=1,
        max_length=255,
        pattern=IDENTIFIER_PATTERN,
        description="Facebook Page/Group ID or username (e.g. '123456789' or 'examplepage').",
    )
    source_url: str | None = Field(default=None, max_length=2048, pattern=URL_PATTERN)
    active: bool = True


class SourceUpdate(_Input):
    source_name: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048, pattern=URL_PATTERN)
    active: bool | None = None


class SourceOut(_Output):
    id: int
    source_type: str
    source_name: str
    source_identifier: str
    source_url: str | None
    active: bool
    last_collected_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SourceValidationOut(BaseModel):
    source_id: int
    ok: bool
    resolved_name: str | None = None
    error_code: str | None = None
    message: str | None = None


# --- Posts ------------------------------------------------------------------
class PostOut(_Output):
    id: int
    source_id: int
    source_name: str
    source_type: str
    external_post_id: str
    posted_at: datetime
    text: str
    collected_at: datetime


# --- Collection -------------------------------------------------------------
class CollectionRunRequest(_Input):
    source_ids: list[int] | None = Field(
        default=None, max_length=1000, description="Limit the run to these source IDs."
    )


class SourceResultOut(BaseModel):
    source_id: int
    source_name: str
    status: str
    window_since: datetime | None
    window_until: datetime | None
    posts_found: int
    posts_saved: int
    posts_skipped: int
    error_code: str | None
    error_message: str | None


class CollectionRunSummaryOut(_Output):
    id: int
    status: RunStatus
    provider: str
    started_at: datetime
    completed_at: datetime | None
    sources_processed: int
    posts_found: int
    posts_saved: int
    posts_skipped: int
    error_count: int
    error_message: str | None


class CollectionRunOut(CollectionRunSummaryOut):
    sources: list[SourceResultOut] = []


class CollectionErrorOut(_Output):
    id: int
    source_id: int | None
    source_name: str | None
    error_code: str
    message: str
    created_at: datetime


class CollectionRunDetailOut(CollectionRunSummaryOut):
    errors: list[CollectionErrorOut] = []


# --- Health -----------------------------------------------------------------
class HealthOut(BaseModel):
    status: str
    version: str
    database: str
    data_provider: str


class ProviderHealthOut(BaseModel):
    ok: bool
    provider: str
    message: str
    details: dict = {}
