from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Post
from app.services.deduplication import CandidatePost, dedupe_batch, filter_new_posts

T = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)


def _candidate(post_id: str, text: str = "hello") -> CandidatePost:
    return CandidatePost(external_post_id=post_id, posted_at=T, text=text)


def _post(source_id: int, post_id: str) -> Post:
    return Post(
        source_id=source_id,
        external_post_id=post_id,
        source_name="S",
        source_type="page",
        posted_at=T,
        text="hello",
        collected_at=T,
    )


def test_dedupe_batch_keeps_first_occurrence():
    unique, dupes = dedupe_batch([_candidate("1", "a"), _candidate("2"), _candidate("1", "b")])
    assert [p.external_post_id for p in unique] == ["1", "2"]
    assert unique[0].text == "a"
    assert dupes == 1


def test_identical_text_with_different_ids_is_not_a_duplicate():
    unique, dupes = dedupe_batch([_candidate("1", "same"), _candidate("2", "same")])
    assert len(unique) == 2
    assert dupes == 0


def test_filter_new_posts_skips_already_stored(session_factory, add_source):
    source_id = add_source("page-a")
    with session_factory() as session, session.begin():
        session.add(_post(source_id, "1"))

    with session_factory() as session:
        new, existing = filter_new_posts(session, source_id, [_candidate("1"), _candidate("2")])
    assert [p.external_post_id for p in new] == ["2"]
    assert existing == 1


def test_same_external_id_in_different_sources_is_allowed(session_factory, add_source):
    a = add_source("page-a")
    b = add_source("page-b")
    with session_factory() as session, session.begin():
        session.add_all([_post(a, "1"), _post(b, "1")])
    with session_factory() as session:
        assert session.query(Post).count() == 2


def test_database_unique_constraint_rejects_duplicates(session_factory, add_source):
    source_id = add_source("page-a")
    with session_factory() as session, session.begin():
        session.add(_post(source_id, "1"))

    with pytest.raises(IntegrityError), session_factory() as session, session.begin():
        session.add(_post(source_id, "1"))
