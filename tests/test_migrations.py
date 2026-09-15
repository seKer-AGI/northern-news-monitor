"""Migrations must build the same schema as the ORM models."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.db import migrate
from app.db.models import Base
from app.db.session import create_engine_from_url


def test_upgrade_matches_models_and_downgrade_cleans_up(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"
    migrate.upgrade(url)

    engine = create_engine_from_url(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert {
            "sources",
            "posts",
            "collection_runs",
            "collection_errors",
            "alembic_version",
        } <= tables

        with engine.connect() as conn:
            diff = compare_metadata(
                MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
            )
        assert diff == [], f"Models and migrations differ: {diff}"

        uniques = inspect(engine).get_unique_constraints("posts")
        assert any(set(u["column_names"]) == {"source_id", "external_post_id"} for u in uniques)
    finally:
        engine.dispose()

    migrate.downgrade(url, "base")
    engine = create_engine_from_url(url)
    try:
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    finally:
        engine.dispose()
