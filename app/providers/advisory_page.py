"""Official advisory pages without an RSS feed (NDMA, PDMA, PMD, ...).

Source type ``advisory_page``; ``source_url`` is the public page listing
advisories. Each run:

1. checks ``robots.txt`` for this User-Agent and refuses if disallowed,
2. fetches the page once and extracts links whose text looks like an advisory,
3. turns each link into an item dated from the date written in its text.

Links without a date (menus, "Flood Maps", plans) get no timestamp, so the
collector's window filter drops them — only newly dated advisories are kept.
"""

from __future__ import annotations

import hashlib
import html
import re
import urllib.robotparser
from datetime import UTC, date, datetime, time, timedelta, timezone
from urllib.parse import urljoin, urlsplit

from app.providers.base import (
    FacebookDataProvider,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
    ProviderPost,
    SourceRef,
    SourceValidation,
)
from app.providers.http_fetch import HttpFetcher

PKT = timezone(timedelta(hours=5), "PKT")

_ANCHOR_RE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NOISE_RE = re.compile(r"\b(?:view|latest|download|read more|click here|new)\b", re.I)
ADVISORY_RE = re.compile(
    r"advis|alert|warning|press release|forecast|sitrep|situation report|bulletin|"
    r"flood|glof|snow|rain|avalanche|landslide|monsoon|heat ?wave|cold ?wave|storm",
    re.I,
)

_MONTHS = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_ORD = r"(?:st|nd|rd|th)?"
# "11 Sep 2026", "22 July 2026", "12th to 17th April, 2026"
_DMY_NAME = re.compile(
    rf"\b(\d{{1,2}}){_ORD}(?:\s+(?:to|-|–)\s+\d{{1,2}}{_ORD})?[\s\-/.,]+{_MONTH}[\s\-/.,]+(\d{{4}})\b",
    re.I,
)
# "September 2, 2026"
_MDY_NAME = re.compile(rf"\b{_MONTH}\s+(\d{{1,2}}){_ORD},?\s+(\d{{4}})\b", re.I)
# "11-09-2026" (day first, as used in Pakistan)
_DMY_NUMERIC = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")


def parse_advisory_date(text: str) -> date | None:
    """Date written in an advisory title, or ``None``."""
    candidates: list[tuple[int, int, int]] = []
    if m := _DMY_NAME.search(text):
        candidates.append((int(m.group(3)), _MONTHS[m.group(2).lower()[:3]], int(m.group(1))))
    if m := _MDY_NAME.search(text):
        candidates.append((int(m.group(3)), _MONTHS[m.group(1).lower()[:3]], int(m.group(2))))
    if m := _DMY_NUMERIC.search(text):
        candidates.append((int(m.group(3)), int(m.group(2)), int(m.group(1))))
    for year, month, day in candidates:
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


_TRAILING_DATE_RE = re.compile(r"\s+(\d{1,2}\s+[A-Za-z]{3,9}\.?,?\s+\d{4})$")


def clean_link_text(raw: str) -> str:
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw))).strip()
    text = _WS_RE.sub(" ", _NOISE_RE.sub(" ", text)).strip(" -–|")
    # Listing pages often repeat the date in a column:
    # "Advisory - 2 Sep 2026 02 Sep 2026" -> "Advisory - 2 Sep 2026"
    trailing = _TRAILING_DATE_RE.search(text)
    if trailing:
        head = text[: trailing.start()]
        head_date = parse_advisory_date(head)
        if head_date is not None and head_date == parse_advisory_date(trailing.group(1)):
            text = head
    return text.strip()


def extract_advisory_links(page_html: str, base_url: str) -> list[tuple[str, str]]:
    """``(absolute_url, text)`` for advisory-looking links, first occurrence per URL."""
    base_norm = base_url.rstrip("/")
    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    for href, inner in _ANCHOR_RE.findall(page_html):
        url = urljoin(base_url, html.unescape(href.strip()))
        if not url.lower().startswith(("http://", "https://")) or url.rstrip("/") == base_norm:
            continue
        text = clean_link_text(inner)
        if len(text) < 12 or not ADVISORY_RE.search(text) or url in seen:
            continue
        seen.add(url)
        links.append((url, text))
    return links


class AdvisoryPageProvider(FacebookDataProvider):
    name = "advisory_pages"
    supported_source_types = frozenset({"advisory_page"})

    def __init__(self, fetcher: HttpFetcher, *, user_agent: str) -> None:
        self._fetcher = fetcher
        self._user_agent = user_agent
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            ok=True, provider=self.name, message="Public official pages need no credentials."
        )

    def validate_source(self, source: SourceRef) -> SourceValidation:
        try:
            links = self._links(source)
        except ProviderError as exc:
            return SourceValidation(ok=False, error_code=exc.code, message=exc.message)
        dated = sum(1 for _, text in links if parse_advisory_date(text))
        return SourceValidation(ok=True, resolved_name=f"{source.name} ({dated} dated advisories)")

    def fetch_posts(
        self, source: SourceRef, since: datetime, until: datetime
    ) -> list[ProviderPost]:
        posts: list[ProviderPost] = []
        for url, text in self._links(source):
            day = parse_advisory_date(text)
            posted_at = None
            if day is not None:
                # Only the day is known: treat it as the end of that day (PKT), never in the future.
                posted_at = min(datetime.combine(day, time(23, 59), PKT).astimezone(UTC), until)
            posts.append(
                ProviderPost(
                    external_post_id=hashlib.sha256(url.encode()).hexdigest()[:40],
                    posted_at=posted_at,
                    text=f"{source.name}: {text}",
                    url=url,
                )
            )
        return posts

    # -- internals --------------------------------------------------------
    def _links(self, source: SourceRef) -> list[tuple[str, str]]:
        if not self.supports(source.source_type):
            raise ProviderError(
                ProviderErrorCode.SOURCE_NOT_SUPPORTED,
                f"Source type {source.source_type!r} is not an advisory page.",
            )
        if not source.url:
            raise ProviderError(
                ProviderErrorCode.INVALID_SOURCE, "Advisory page has no source_url."
            )
        if not self._allowed(source.url):
            raise ProviderError(
                ProviderErrorCode.PERMISSION_DENIED,
                "robots.txt of this site does not allow automated reading of this page.",
            )
        result = self._fetcher.get(source.url, operation=f"advisory:{source.identifier}")
        return extract_advisory_links(result.content.decode("utf-8", "replace"), result.url)

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(root)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            try:
                result = self._fetcher.get(f"{root}/robots.txt", operation="robots")
                parser.parse(result.content.decode("utf-8", "replace").splitlines())
            except ProviderError as exc:
                if exc.code == ProviderErrorCode.INVALID_SOURCE:  # no robots.txt: allowed
                    parser.parse([])
                elif (
                    exc.code == ProviderErrorCode.PERMISSION_DENIED
                ):  # robots.txt refused: stay out
                    parser.parse(["User-agent: *", "Disallow: /"])
                else:
                    raise  # temporary failure: fail this run, retry next time
            self._robots[root] = parser
        return parser.can_fetch(self._user_agent, url)

    def close(self) -> None:
        self._fetcher.close()
