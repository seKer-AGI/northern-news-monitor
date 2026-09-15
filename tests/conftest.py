from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Base, Source
from app.db.session import create_engine_from_url, make_session_factory

# Tests must never read a developer's real .env or Meta credentials.
for _var in ("META_ACCESS_TOKEN", "META_APP_SECRET", "INTERNAL_API_KEY", "DATA_PROVIDER"):
    os.environ.pop(_var, None)

TEST_API_KEY = "test-internal-key-123"


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 9, 14, 12, 0, tzinfo=UTC))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        data_provider="mock",
        internal_api_key=TEST_API_KEY,
        log_format="text",
        notification_provider="none",
        provider_backoff_base_seconds=0,
        provider_backoff_max_seconds=0,
        fetch_overlap_minutes=10,
        initial_lookback_hours=24,
    )


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    engine = create_engine_from_url(settings.database_url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def add_source(session_factory: sessionmaker[Session]):
    def _add(
        identifier: str, source_type: str = "page", name: str | None = None, active: bool = True
    ) -> int:
        with session_factory() as session, session.begin():
            source = Source(
                source_type=source_type,
                source_name=name or identifier.replace("-", " ").title(),
                source_identifier=identifier,
                source_url=f"https://www.facebook.com/{identifier}",
                active=active,
            )
            session.add(source)
            session.flush()
            return source.id

    return _add
