"""Default northern-areas weather/hazard news sources.

Every URL here was fetched and parsed successfully before being added.
Google News queries are split by region because one giant query gets
truncated; a leading ``when:2d`` keeps results recent (the collector re-filters
anyway). Re-running the seed command refreshes the URLs of existing seed
sources, so query fixes reach an already-seeded database.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Source
from app.providers.weather import NORTHERN_LOCATIONS

HAZARD_QUERY = (
    '(snow OR snowfall OR rain OR flood OR "flash flood" OR landslide OR avalanche OR glacier '
    'OR GLOF OR cloudburst OR "road closed" OR "road blocked" OR bridge OR stranded OR weather)'
)


def google_news_url(locations_expr: str) -> str:
    # ``when:`` must come FIRST: at the end of a long query Google News ignores it
    # and returns months-old stories (verified 2026-09-15: 3/100 recent vs 22/22).
    query = f"when:2d {locations_expr} {HAZARD_QUERY}"
    return "https://news.google.com/rss/search?" + urlencode(
        {"q": query, "hl": "en-PK", "gl": "PK", "ceid": "PK:en"}
    )


@dataclass(frozen=True, slots=True)
class SeedSource:
    source_type: str
    identifier: str
    name: str
    url: str | None = None


NORTHERN_SEEDS: tuple[SeedSource, ...] = (
    # Google News search feeds (aggregate Dawn, Tribune, Geo, Jang, Nawa-i-Waqt, ...)
    SeedSource(
        "google_news",
        "gn-hazara-galiyat-kaghan",
        "Google News: Murree / Galiyat / Kaghan / Naran",
        google_news_url(
            '(Murree OR Galiyat OR "Nathia Gali" OR Abbottabad OR Mansehra OR Balakot '
            "OR Kaghan OR Naran OR Babusar)"
        ),
    ),
    SeedSource(
        "google_news",
        "gn-swat-chitral-kohistan",
        "Google News: Swat / Chitral / Dir / Kohistan",
        google_news_url(
            '(Swat OR Kalam OR "Malam Jabba" OR Chitral OR "Upper Dir" OR "Lower Dir" '
            "OR Shangla OR Kohistan OR Besham)"
        ),
    ),
    SeedSource(
        "google_news",
        "gn-gilgit-baltistan",
        "Google News: Gilgit-Baltistan / KKH",
        google_news_url(
            "(Gilgit OR Hunza OR Skardu OR Astore OR Chilas OR Diamer OR Ghizer OR Khunjerab "
            'OR Deosai OR "Karakoram Highway" OR "Gilgit-Baltistan")'
        ),
    ),
    SeedSource(
        "google_news",
        "gn-azad-kashmir",
        "Google News: Neelum / Muzaffarabad / AJK",
        google_news_url('(Neelum OR Muzaffarabad OR "Azad Kashmir" OR AJK OR Rawalakot)'),
    ),
    SeedSource(
        "google_news",
        "gn-ndma-pdma-pmd-alerts",
        "Google News: NDMA / PDMA / PMD alerts (north)",
        google_news_url('(NDMA OR PDMA OR PMD OR "Met Office")'),
    ),
    # Rescue 1122 and road authorities. Their own sites can't be read automatically
    # (NHA returns 403, NHMP refuses connections, Rescue 1122 GB feed is years old),
    # so their news is followed through Google News instead.
    SeedSource(
        "google_news",
        "gn-rescue1122-north",
        "Google News: Rescue 1122 (north)",
        google_news_url(
            '("Rescue 1122" OR Rescue1122) (Swat OR Chitral OR Kohistan OR Mansehra OR Murree '
            'OR Gilgit OR Skardu OR Hunza OR "Upper Dir" OR "Lower Dir" OR Shangla OR Neelum '
            "OR Naran OR Kaghan OR Abbottabad OR Diamer)"
        ),
    ),
    SeedSource(
        "google_news",
        "gn-roads-nha-nhmp-north",
        "Google News: NHA / NHMP / FWO roads (north)",
        google_news_url(
            '(NHA OR "National Highway Authority" OR NHMP OR "Motorway Police" OR FWO) '
            '(KKH OR "Karakoram Highway" OR Babusar OR Naran OR Kaghan OR Lowari OR Shandur '
            'OR "Chitral road" OR "Neelum road" OR "Swat Expressway" OR "Murree Expressway" '
            'OR "Hazara Motorway")'
        ),
    ),
    # Publisher RSS feeds (English + Urdu + Gilgit-Baltistan local)
    SeedSource("rss", "dawn-pakistan", "Dawn — Pakistan", "https://www.dawn.com/feeds/pakistan"),
    SeedSource(
        "rss",
        "tribune-pakistan",
        "Express Tribune — Pakistan",
        "https://tribune.com.pk/feed/pakistan",
    ),
    SeedSource("rss", "geo-news", "Geo News", "https://www.geo.tv/rss/1/1"),
    SeedSource("rss", "ary-news", "ARY News", "https://arynews.tv/feed/"),
    SeedSource("rss", "jang-urdu", "Daily Jang (Urdu)", "https://jang.com.pk/rss/1/1"),
    SeedSource("rss", "express-urdu", "Express (Urdu)", "https://www.express.pk/feed/"),
    SeedSource(
        "rss", "pamir-times", "Pamir Times (Gilgit-Baltistan)", "https://pamirtimes.net/feed/"
    ),
    # Local Chitral / Gilgit-Baltistan outlets (feeds verified 2026-09-15, robots.txt allows)
    SeedSource(
        "rss", "chitral-times-urdu", "Chitral Times (Urdu)", "https://chitraltimes.com/feed"
    ),
    SeedSource(
        "rss",
        "chitral-times-english",
        "Chitral Times (English)",
        "https://english.chitraltimes.com/feed/",
    ),
    SeedSource("rss", "chitral-today", "Chitral Today", "https://chitraltoday.net/feed/"),
    SeedSource("rss", "daily-k2", "Daily K2 (Gilgit-Baltistan)", "https://dailyk2.com/feed/"),
    SeedSource("rss", "skardu-pk", "Skardu.pk (Baltistan)", "https://skardu.pk/feed/"),
    # Official advisory pages without RSS (robots.txt allows; dated links verified 2026-09-15).
    # GBDMA (PDMA Gilgit-Baltistan) is not included: gbdma.gog.pk does not resolve.
    SeedSource("advisory_page", "ndma-advisories", "NDMA", "https://www.ndma.gov.pk/advisories"),
    SeedSource("advisory_page", "pdma-kp", "PDMA Khyber Pakhtunkhwa", "https://www.pdma.gov.pk"),
    SeedSource(
        "advisory_page",
        "pmd-press-releases",
        "PMD Press Release",
        "https://weather.gov.pk/nwfc/all-press-releases",
    ),
    # Forecast alerts
    *(
        SeedSource("weather", loc.slug, f"Weather: {loc.name}")
        for loc in NORTHERN_LOCATIONS.values()
    ),
)


def seed_sources(
    session: Session, seeds: tuple[SeedSource, ...] = NORTHERN_SEEDS
) -> tuple[int, int]:
    """Insert missing seed sources and refresh seed URLs. Returns ``(created, already_present)``.

    Idempotent. Only ``source_url`` of an existing seed is refreshed; its name,
    ``active`` flag and collection watermark are left untouched.
    """
    existing = {(s.source_type, s.source_identifier): s for s in session.scalars(select(Source))}
    created = 0
    for seed in seeds:
        current = existing.get((seed.source_type, seed.identifier))
        if current is not None:
            if seed.url and current.source_url != seed.url:
                current.source_url = seed.url
            continue
        session.add(
            Source(
                source_type=seed.source_type,
                source_name=seed.name,
                source_identifier=seed.identifier,
                source_url=seed.url,
                active=True,
            )
        )
        created += 1
    session.commit()
    return created, len(seeds) - created
