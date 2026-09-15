"""Advisory-page provider: date parsing, link extraction, robots.txt, collection."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.db import migrate
from app.db.models import Post, Source
from app.db.session import create_engine_from_url, make_session_factory
from app.providers.advisory_page import (
    AdvisoryPageProvider,
    clean_link_text,
    extract_advisory_links,
    parse_advisory_date,
)
from app.providers.base import ProviderError, ProviderErrorCode, SourceRef
from app.providers.http_fetch import HttpFetcher
from app.providers.retry import RetryPolicy
from app.services.collection import CollectionService

UA = "facebook-post-monitor/0.1 (test)"
PAGE_URL = "https://www.ndma.gov.pk/advisories"
PAGE = """
<nav><a href="https://ndma.gov.pk/advisories">Advisories</a>
<a href="/maps/6">Flood Maps</a>
<a href="mailto:info@ndma.gov.pk">Email weather advisory desk</a></nav>
<table>
<tr><td><a href="//www.ndma.gov.pk/storage/advisories/September2026/a.pdf">
    NDMA Weather Advisory - 14 Sep 2026 <span>Latest</span> 14 Sep 2026 View</a></td></tr>
<tr><td><a href="/storage/advisories/September2026/b.pdf">NDMA Weather Advisory - 2 Sep 2026 View</a></td></tr>
<tr><td><a href="/storage/advisories/September2026/b.pdf">NDMA Weather Advisory - 2 Sep 2026 View</a></td></tr>
<tr><td><a href="/storage/plans/plan.pdf">National Disaster Response Plan (monsoon)</a></td></tr>
</table>
"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("NDMA Weather Advisory - 11 Sep 2026 Latest 11 Sep 2026 View", date(2026, 9, 11)),
        ("NDMA Flash Flood Advisory (KP & GB) - 22 July 2026", date(2026, 7, 22)),
        ("Weather Advisory (12th to 17th April, 2026)", date(2026, 4, 12)),
        ("Weather Advisory 11-09-2026", date(2026, 9, 11)),
        ("Press release September 2, 2026", date(2026, 9, 2)),
        ("Flood Maps", None),
        ("Advisory 31-02-2026", None),
    ],
)
def test_parse_advisory_date(text, expected):
    assert parse_advisory_date(text) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "NDMA Weather Advisory - 11 Sep 2026 <b>Latest</b> 11 Sep 2026 View",
            "NDMA Weather Advisory - 11 Sep 2026",
        ),
        ("NDMA Weather Advisory - 2 Sep 2026 02 Sep 2026", "NDMA Weather Advisory - 2 Sep 2026"),
        (
            "NDMA Weather Advisory dated 16 August 2026 16 Aug 2026",
            "NDMA Weather Advisory dated 16 August 2026",
        ),
        # A single trailing date is the only date: keep it.
        ("Rain predicted in upper parts 11 Sep 2026", "Rain predicted in upper parts 11 Sep 2026"),
        # Different dates are not duplicates.
        ("Advisory 1 Sep 2026 2 Sep 2026", "Advisory 1 Sep 2026 2 Sep 2026"),
    ],
)
def test_clean_link_text_removes_noise_and_repeated_date(raw, expected):
    assert clean_link_text(raw) == expected


def test_extract_advisory_links_filters_menus_and_duplicates():
    links = extract_advisory_links(PAGE, PAGE_URL)
    assert links == [
        (
            "https://www.ndma.gov.pk/storage/advisories/September2026/a.pdf",
            "NDMA Weather Advisory - 14 Sep 2026",
        ),
        (
            "https://www.ndma.gov.pk/storage/advisories/September2026/b.pdf",
            "NDMA Weather Advisory - 2 Sep 2026",
        ),
        (
            "https://www.ndma.gov.pk/storage/plans/plan.pdf",
            "National Disaster Response Plan (monsoon)",
        ),
    ]


def _provider(robots: str | int = "User-agent: *\nDisallow: /admin\n", page: str = PAGE):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            if isinstance(robots, int):
                return httpx.Response(robots)
            return httpx.Response(200, text=robots)
        return httpx.Response(200, text=page)

    fetcher = HttpFetcher(
        user_agent=UA,
        timeout=5,
        retry=RetryPolicy(max_retries=0, base_delay=0, max_delay=0),
        max_bytes=100_000,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return AdvisoryPageProvider(fetcher, user_agent=UA), requested


REF = SourceRef("advisory_page", "ndma-advisories", "NDMA", PAGE_URL)
UNTIL = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def test_fetch_posts_dates_items_and_caps_to_until():
    provider, _ = _provider()
    posts = provider.fetch_posts(REF, UNTIL - timedelta(days=1), UNTIL)
    by_text = {p.text: p for p in posts}

    today = by_text["NDMA: NDMA Weather Advisory - 14 Sep 2026"]
    assert today.posted_at == UNTIL  # end of 14 Sep PKT is after "until" → capped
    older = by_text["NDMA: NDMA Weather Advisory - 2 Sep 2026"]
    assert older.posted_at == datetime(2026, 9, 2, 18, 59, tzinfo=UTC)  # 23:59 PKT
    undated = by_text["NDMA: National Disaster Response Plan (monsoon)"]
    assert undated.posted_at is None
    assert today.url.endswith("a.pdf") and len(today.external_post_id) == 40


def test_robots_disallow_is_respected_without_fetching_page():
    provider, requested = _provider(robots="User-agent: *\nDisallow: /\n")
    with pytest.raises(ProviderError) as exc:
        provider.fetch_posts(REF, UNTIL, UNTIL)
    assert exc.value.code == ProviderErrorCode.PERMISSION_DENIED
    assert requested == ["/robots.txt"]


def test_missing_robots_allows_but_forbidden_robots_blocks():
    allowed, _ = _provider(robots=404)
    assert allowed.fetch_posts(REF, UNTIL, UNTIL)
    blocked, requested = _provider(robots=403)
    assert not blocked.validate_source(REF).ok
    assert requested == ["/robots.txt"]


def test_validate_source_counts_dated_advisories():
    provider, _ = _provider()
    result = provider.validate_source(REF)
    assert result.ok and "2 dated advisories" in result.resolved_name


def test_collection_keeps_official_advisories_without_keywords(session_factory, settings, clock):
    with session_factory() as session, session.begin():
        session.add(
            Source(
                source_type="advisory_page",
                source_name="NDMA",
                source_identifier="ndma-advisories",
                source_url=PAGE_URL,
            )
        )
    provider, _ = _provider()
    result = CollectionService(session_factory, provider, settings, clock=clock).run()

    assert result.status == "success"
    assert result.posts_saved == 1  # 14 Sep advisory; 2 Sep outside window; undated dropped
    with session_factory() as session:
        post = session.scalars(select(Post)).one()
    assert post.text == "NDMA: NDMA Weather Advisory - 14 Sep 2026"
    assert post.hazards == "Official advisory; Weather"
    assert post.url.endswith("a.pdf")


def test_migration_0003_accepts_advisory_page(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm3.db').as_posix()}"
    migrate.upgrade(url, "head")
    engine = create_engine_from_url(url)
    try:
        with make_session_factory(engine)() as session, session.begin():
            session.add(
                Source(
                    source_type="advisory_page",
                    source_name="NDMA",
                    source_identifier="ndma",
                    source_url=PAGE_URL,
                )
            )
    finally:
        engine.dispose()
    migrate.downgrade(url, "0002")
    engine = create_engine_from_url(url)
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM sources").scalar() == 0
    finally:
        engine.dispose()
