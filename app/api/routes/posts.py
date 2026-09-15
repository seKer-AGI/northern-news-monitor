from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import DbSession, Filters, require_api_key
from app.api.schemas import Paginated, PostOut
from app.core.exceptions import NotFoundError
from app.db.models import Post
from app.services.posts import list_posts

router = APIRouter(prefix="/api/v1/posts", tags=["posts"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=Paginated[PostOut])
def get_posts(
    db: DbSession,
    filters: Filters,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Paginated[PostOut]:
    posts, total = list_posts(db, filters, page=page, page_size=page_size)
    items = [PostOut.model_validate(p) for p in posts]
    return Paginated[PostOut].build(items, total, page, page_size)


@router.get("/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: DbSession) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise NotFoundError(f"Post {post_id} not found.")
    return post
