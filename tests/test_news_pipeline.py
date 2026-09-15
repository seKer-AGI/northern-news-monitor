"""End-to-end news/weather pipeline: collection, relevance, storage, seeds, export, CLI, API."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app.cli import EXIT_OK, Context, main
from app.db import migrate
from app.db.models import Post, Source
from app.db.session import create_engine_from_url, make_session_factory
from app.main import create_app
from app.providers.base import (
    FacebookDataProvider,
    ProviderHealth,
    ProviderPost,
    SourceValidation,
)
from app.providers.mock import MockFacebookProvider
from app.providers.routing import RoutingProvider
from app.services.collection import CollectionService
from app.services.export import NEWS_EXPORT_COLUMNS, iter_news_rows, news_story_key, to_csv
from app.services.posts import PostFilters
from app.services.seeds import NORTHERN_SEEDS, seed_sources
from tests.conftest import TEST_API_KEY


class FakeNewsProvider(FacebookDataProvider):
    name = "fake_news"
    supported_source_types = frozenset({"rss", "google_news", "weather"})

    def __init__(self, posts_by_identifier):
        self.posts_by_identifier = posts_by_identifier
        self.seen_urls = []

    def fetch_posts(self, source, since, until):
        self.seen_urls.append(source.url)
        return list(self.posts_by_identifier.get(source.identifier, []))

    def validate_source(self, source):
        return SourceValidation(ok=True, resolved_name=source.name)

    def health_check(self):
        return ProviderHealth(ok=True, provider=self.name, message="ok")


def _add(session_factory, source_type, identifier, name, url=None):
    with session_factory() as session, session.begin():
        source = Source(
            source_type=source_type,
            source_name=name,
            source_identifier=identifier,
            source_url=url,
        )
        session.add(source)
        session.flush()
        return source.id


@pytest.fixture
def news_posts(clock):
    now = clock.now
    return {
        "dawn": [
            ProviderPost(
                "d1",
                now - timedelta(hours=2),
                "Heavy snowfall blocks Babusar Top - Dawn",
                "https://dawn.com/1",
            ),
            ProviderPost(
                "d2",
                now - timedelta(hours=3),
                "PM chairs federal cabinet meeting",
                "https://dawn.com/2",
            ),
            ProviderPost("d3", now - timedelta(days=5), "Old flood in Swat", "https://dawn.com/3"),
        ],
        "gn": [
            ProviderPost(
                "g1",
                now - timedelta(hours=1),
                "Heavy snowfall blocks Babusar Top - tribune.com.pk",
                "https://news.google.com/a",
            ),
            ProviderPost(
                "g2",
                now - timedelta(hours=4),
                "=Landslide in Chitral closes road",
                "https://news.google.com/b",
            ),
        ],
    }


def test_news_collection_filters_relevance_and_stores_url(
    session_factory, settings, clock, news_posts
):
    _add(session_factory, "rss", "dawn", "Dawn", "https://www.dawn.com/feeds/pakistan")
    _add(
        session_factory,
        "google_news",
        "gn",
        "Google News",
        "https://news.google.com/rss/search?q=x",
    )
    fb_id = _add(session_factory, "page", "fb-page", "FB Page")
    provider = RoutingProvider(
        {
            "page": MockFacebookProvider(
                clock=clock,
                posts_by_source={
                    "fb-page": [
                        ProviderPost("f1", clock.now - timedelta(hours=1), "PM chairs meeting")
                    ]
                },
            ),
            **dict.fromkeys(("rss", "google_news", "weather"), FakeNewsProvider(news_posts)),
        }
    )

    result = CollectionService(session_factory, provider, settings, clock=clock).run()

    assert result.status == "success"
    by_source = {s.source_name: s for s in result.sources}
    assert (
        by_source["Dawn"].posts_saved == 1
    )  # cabinet meeting irrelevant, old flood outside window
    assert by_source["Dawn"].posts_skipped == 2
    assert by_source["Google News"].posts_saved == 2
    assert by_source["FB Page"].posts_saved == 1  # Facebook text is NOT relevance-filtered

    with session_factory() as session:
        dawn = session.scalars(select(Post).where(Post.external_post_id == "d1")).one()
        assert dawn.url == "https://dawn.com/1"
        assert dawn.locations == "Babusar"
        assert dawn.hazards == "Snow"
        fb_post = session.scalars(select(Post).where(Post.source_id == fb_id)).one()
        assert fb_post.url is None and fb_post.locations is None


def test_news_export_collapses_same_story_and_formats_pkt(
    session_factory, settings, clock, news_posts
):
    _add(session_factory, "rss", "dawn", "Dawn", "https://www.dawn.com/feeds/pakistan")
    _add(
        session_factory,
        "google_news",
        "gn",
        "Google News",
        "https://news.google.com/rss/search?q=x",
    )
    provider = FakeNewsProvider(news_posts)
    CollectionService(session_factory, provider, settings, clock=clock).run()

    with session_factory() as session:
        rows = list(iter_news_rows(session, PostFilters()))
        undeduped = list(iter_news_rows(session, PostFilters(), dedupe=False))
        csv_text = to_csv(iter_news_rows(session, PostFilters()), fieldnames=NEWS_EXPORT_COLUMNS)

    assert len(undeduped) == 3 and len(rows) == 2
    assert rows[0]["text"].startswith("Heavy snowfall blocks Babusar Top")  # newest first
    assert rows[0]["posted_at_pkt"] == "2026-09-14 16:00"  # 11:00 UTC → 16:00 PKT

    parsed = list(csv.DictReader(io.StringIO(csv_text.lstrip("﻿"))))
    assert tuple(parsed[0].keys()) == NEWS_EXPORT_COLUMNS
    landslide = next(r for r in parsed if "Landslide" in r["text"])
    assert landslide["text"].startswith("'=")  # formula escaped
    assert landslide["url"] == "https://news.google.com/b"  # url untouched
    assert landslide["locations"] == "Chitral"


def test_collected_since_limits_daily_export(session_factory, settings, clock, news_posts):
    _add(session_factory, "rss", "dawn", "Dawn", "https://www.dawn.com/feeds/pakistan")
    CollectionService(session_factory, FakeNewsProvider(news_posts), settings, clock=clock).run()
    with session_factory() as session:
        assert (
            len(
                list(
                    iter_news_rows(
                        session, PostFilters(), collected_since=clock.now - timedelta(hours=1)
                    )
                )
            )
            == 1
        )
        assert (
            list(
                iter_news_rows(
                    session, PostFilters(), collected_since=clock.now + timedelta(hours=1)
                )
            )
            == []
        )


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (
            "Heavy snowfall blocks Babusar Top - Dawn",
            "Heavy snowfall blocks Babusar Top - tribune.com.pk",
        ),
        ("Glof, cloudburst ravage Chitral | Dawn", "Glof cloudburst ravage Chitral"),
    ],
)
def test_story_key_ignores_publisher_suffix(a, b):
    assert news_story_key(a) == news_story_key(b)


def test_seed_sources_is_idempotent(session_factory):
    with session_factory() as session:
        created, existing = seed_sources(session)
    assert created == len(NORTHERN_SEEDS) and existing == 0
    with session_factory() as session:
        assert seed_sources(session) == (0, len(NORTHERN_SEEDS))
        types = set(session.scalars(select(Source.source_type)))
        feeds_without_url = session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.source_type.in_(["rss", "google_news"]), Source.source_url.is_(None))
        )
    assert types == {"rss", "google_news", "weather"}
    assert feeds_without_url == 0


def test_migration_0002_accepts_news_sources_and_downgrades(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    migrate.upgrade(url, "head")
    engine = create_engine_from_url(url)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("posts")}
        assert {"url", "locations", "hazards"} <= cols
        factory = make_session_factory(engine)
        with factory() as session, session.begin():
            session.add(Source(source_type="weather", source_name="W", source_identifier="murree"))
    finally:
        engine.dispose()

    migrate.downgrade(url, "0001")
    engine = create_engine_from_url(url)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("posts")}
        assert "url" not in cols
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM sources").scalar() == 0
    finally:
        engine.dispose()


# --- CLI / API -------------------------------------------------------------------
@pytest.fixture
def cli_ctx(settings, session_factory, clock, news_posts):
    return Context(
        settings=settings,
        _session_factory=session_factory,
        provider_factory=lambda _s: FakeNewsProvider(news_posts),
        out=io.StringIO(),
        clock=clock,
    )


def _run(ctx, *argv):
    ctx.out.seek(0)
    ctx.out.truncate()
    return main(list(argv), context=ctx), ctx.out.getvalue()


def test_cli_rss_source_requires_url(cli_ctx):
    code, _ = _run(
        cli_ctx, "sources", "add", "--type", "rss", "--name", "Dawn", "--identifier", "dawn"
    )
    assert code != EXIT_OK
    code, _ = _run(
        cli_ctx,
        "sources",
        "add",
        "--type",
        "rss",
        "--name",
        "Dawn",
        "--identifier",
        "dawn",
        "--url",
        "https://www.dawn.com/feeds/pakistan",
    )
    assert code == EXIT_OK


def test_cli_seed_and_news_csv_export(cli_ctx, tmp_path):
    code, out = _run(cli_ctx, "sources", "seed-northern")
    assert code == EXIT_OK and "added" in out
    _run(
        cli_ctx,
        "sources",
        "add",
        "--type",
        "rss",
        "--name",
        "Dawn",
        "--identifier",
        "dawn",
        "--url",
        "https://www.dawn.com/feeds/pakistan",
    )
    code, out = _run(cli_ctx, "collect")
    assert json.loads(out)["posts_saved"] >= 1

    target = tmp_path / "out" / "news.csv"
    code, out = _run(cli_ctx, "export", "news-csv", "--output", str(target))
    assert code == EXIT_OK
    rows = list(csv.DictReader(io.StringIO(target.read_text(encoding="utf-8").lstrip("﻿"))))
    assert rows and rows[0]["hazards"]


def test_api_news_csv_and_feed_source_validation(settings, session_factory, clock, news_posts):
    app = create_app(
        settings,
        session_factory=session_factory,
        provider_factory=lambda _s: FakeNewsProvider(news_posts),
        clock=clock,
        setup_logging=False,
    )
    auth = {"Authorization": f"Bearer {TEST_API_KEY}"}
    with TestClient(app) as client:
        missing_url = client.post(
            "/api/v1/sources",
            json={"source_type": "rss", "source_name": "Dawn", "source_identifier": "dawn"},
            headers=auth,
        )
        assert missing_url.status_code == 422
        created = client.post(
            "/api/v1/sources",
            json={
                "source_type": "rss",
                "source_name": "Dawn",
                "source_identifier": "dawn",
                "source_url": "https://www.dawn.com/feeds/pakistan",
            },
            headers=auth,
        )
        assert created.status_code == 201
        assert client.post("/api/v1/collection/run", headers=auth).json()["posts_saved"] == 1

        response = client.get("/api/v1/export/news-csv?since_hours=24", headers=auth)
        assert response.status_code == 200
        assert "northern-weather-news" in response.headers["content-disposition"]
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert [r["locations"] for r in rows] == ["Babusar"]


def test_now_fixture_sanity(clock):
    assert clock.now == datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
