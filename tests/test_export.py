import csv
import io
import json
from datetime import UTC, datetime

from app.db.models import Post
from app.services.export import EXPORT_COLUMNS, iter_export_rows, to_csv
from app.services.posts import PostFilters


def _seed(session_factory, source_id, rows):
    with session_factory() as session, session.begin():
        for i, (posted_at, text) in enumerate(rows):
            session.add(
                Post(
                    source_id=source_id,
                    external_post_id=f"p{i}",
                    source_name="Example Group",
                    source_type="group",
                    posted_at=posted_at,
                    text=text,
                    raw_text="should never be exported",
                    collected_at=posted_at,
                )
            )


def test_export_rows_contain_only_minimal_fields(session_factory, add_source):
    source_id = add_source("g", "group")
    _seed(
        session_factory,
        source_id,
        [(datetime(2026, 9, 14, 10, 30, tzinfo=UTC), "Looking for an AI developer...")],
    )
    with session_factory() as session:
        rows = list(iter_export_rows(session, PostFilters()))
    assert rows == [
        {
            "source_name": "Example Group",
            "source_type": "group",
            "posted_at": "2026-09-14T10:30:00Z",
            "text": "Looking for an AI developer...",
        }
    ]
    assert json.loads(json.dumps(rows)) == rows


def test_csv_preserves_unicode_newlines_and_commas(session_factory, add_source):
    source_id = add_source("g", "group")
    text = 'Need help, urgently 🙏\nکیا کوئی "developer" ہے؟'
    _seed(session_factory, source_id, [(datetime(2026, 9, 14, tzinfo=UTC), text)])
    with session_factory() as session:
        output = to_csv(iter_export_rows(session, PostFilters()))
    assert output.startswith("﻿")
    rows = list(csv.DictReader(io.StringIO(output.lstrip("﻿"))))
    assert tuple(rows[0].keys()) == EXPORT_COLUMNS
    assert rows[0]["text"] == text


def test_csv_escapes_spreadsheet_formulas(session_factory, add_source):
    source_id = add_source("g", "group")
    _seed(
        session_factory, source_id, [(datetime(2026, 9, 14, tzinfo=UTC), '=HYPERLINK("http://x")')]
    )
    with session_factory() as session:
        escaped = to_csv(iter_export_rows(session, PostFilters()))
    with session_factory() as session:
        raw = to_csv(iter_export_rows(session, PostFilters()), escape_formulas=False)
    assert "'=HYPERLINK" in escaped
    assert "'=HYPERLINK" not in raw


def test_export_filters_by_date(session_factory, add_source):
    source_id = add_source("g", "group")
    _seed(
        session_factory,
        source_id,
        [
            (datetime(2026, 9, 13, 23, 0, tzinfo=UTC), "old"),
            (datetime(2026, 9, 14, 9, 0, tzinfo=UTC), "new"),
        ],
    )
    filters = PostFilters(start_date=datetime(2026, 9, 14, tzinfo=UTC))
    with session_factory() as session:
        assert [r["text"] for r in iter_export_rows(session, filters)] == ["new"]
