from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.db.models import Source
from app.services.seeds import NORTHERN_SEEDS, google_news_url, seed_sources


def test_google_news_query_starts_with_recency_operator():
    query = parse_qs(urlparse(google_news_url("(Gilgit OR Hunza)")).query)["q"][0]
    assert query.startswith("when:2d ")


def test_all_google_news_seeds_put_when_first():
    for seed in NORTHERN_SEEDS:
        if seed.source_type == "google_news":
            assert parse_qs(urlparse(seed.url).query)["q"][0].startswith("when:")


def test_reseeding_refreshes_urls_but_keeps_user_settings(session_factory):
    seed = next(s for s in NORTHERN_SEEDS if s.source_type == "google_news")
    with session_factory() as session:
        seed_sources(session)
    with session_factory() as session, session.begin():
        source = session.scalars(
            select(Source).where(Source.source_identifier == seed.identifier)
        ).one()
        source.source_url = "https://news.google.com/rss/search?q=old+query+when:2d"
        source.active = False
        source.source_name = "Renamed by user"

    with session_factory() as session:
        assert seed_sources(session) == (0, len(NORTHERN_SEEDS))
    with session_factory() as session:
        source = session.scalars(
            select(Source).where(Source.source_identifier == seed.identifier)
        ).one()
    assert source.source_url == seed.url
    assert source.active is False
    assert source.source_name == "Renamed by user"
