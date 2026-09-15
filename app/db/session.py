"""Engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def create_engine_from_url(url: str, **kwargs: Any) -> Engine:
    if url.startswith("sqlite"):
        kwargs.setdefault("connect_args", {"check_same_thread": False})
        engine = create_engine(url, **kwargs)

        # SQLite is only used for tests / quick local experiments. This is the
        # documented SQLAlchemy recipe that makes SAVEPOINT work with pysqlite.
        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn: Any, _: Any) -> None:
            dbapi_conn.isolation_level = None
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _on_begin(conn: Any) -> None:
            conn.exec_driver_sql("BEGIN")

        return engine
    kwargs.setdefault("pool_pre_ping", True)
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@lru_cache
def get_engine() -> Engine:
    return create_engine_from_url(get_settings().database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_engine())


def session_scope() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
