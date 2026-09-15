"""RSS / Atom feed provider (news websites and Google News search feeds).

Source types:
  * ``rss``         — a publisher's public RSS/Atom feed (``source_url``)
  * ``google_news`` — a Google News RSS search URL (``source_url``)

Feeds are public, machine-readable endpoints published for exactly this kind
of consumption. XML is parsed with ``defusedxml`` (no entity expansion attacks).
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from defusedxml import ElementTree as SafeET

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

PKT = timezone(timedelta(hours=5), "PKT")  # Pakistan has no DST
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class FeedItem:
    key: str
    title: str
    summary: str
    link: str | None
    published: datetime | None


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(elem: Any, *names: str) -> Any | None:
    for child in elem:
        if _local(child.tag) in names:
            return child
    return None


def _child_text(elem: Any, *names: str) -> str:
    child = _child(elem, *names)
    return "".join(child.itertext()).strip() if child is not None else ""


def html_to_text(value: str) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value))).strip()


def parse_feed_datetime(value: str | None, default_tz: timezone = PKT) -> datetime | None:
    """Parse RFC 822 / ISO 8601 / common variants. Naive values use ``default_tz``."""
    if not value:
        return None
    raw = value.strip()
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d %b %Y %H:%M:%S", "%a, %d %b %Y %H:%M"):
                try:
                    parsed = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(UTC)


def parse_feed(content: bytes, default_tz: timezone = PKT) -> tuple[str | None, list[FeedItem]]:
    try:
        root = SafeET.fromstring(content)
    except Exception as exc:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_ERROR, "Response is not a valid RSS/Atom feed."
        ) from exc

    kind = _local(root.tag)
    items: list[FeedItem] = []
    if kind in ("rss", "RDF"):
        channel = _child(root, "channel")
        title = _child_text(channel, "title") if channel is not None else None
        for node in root.iter():
            if _local(node.tag) != "item":
                continue
            link = _child_text(node, "link") or None
            guid = _child_text(node, "guid")
            item_title = html_to_text(_child_text(node, "title"))
            published_raw = _child_text(node, "pubDate", "date", "published", "updated")
            items.append(
                FeedItem(
                    key=guid or link or f"{item_title}|{published_raw}",
                    title=item_title,
                    summary=html_to_text(_child_text(node, "description")),
                    link=link,
                    published=parse_feed_datetime(published_raw, default_tz),
                )
            )
    elif kind == "feed":
        title = _child_text(root, "title")
        for node in root:
            if _local(node.tag) != "entry":
                continue
            link = None
            for child in node:
                if _local(child.tag) == "link" and child.get("rel") in (None, "alternate"):
                    link = child.get("href")
                    break
            item_title = html_to_text(_child_text(node, "title"))
            published_raw = _child_text(node, "published", "updated")
            items.append(
                FeedItem(
                    key=_child_text(node, "id") or link or f"{item_title}|{published_raw}",
                    title=item_title,
                    summary=html_to_text(_child_text(node, "summary", "content")),
                    link=link,
                    published=parse_feed_datetime(published_raw, default_tz),
                )
            )
    else:
        raise ProviderError(ProviderErrorCode.PROVIDER_ERROR, "Unrecognised feed format.")
    return title, items


def stable_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


class FeedProvider(FacebookDataProvider):
    name = "feeds"
    supported_source_types = frozenset({"rss", "google_news"})

    def __init__(self, fetcher: HttpFetcher, *, summary_chars: int = 600) -> None:
        self._fetcher = fetcher
        self._summary_chars = summary_chars

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            ok=True, provider=self.name, message="Public feeds need no credentials."
        )

    def validate_source(self, source: SourceRef) -> SourceValidation:
        try:
            title, _ = self._load(source)
        except ProviderError as exc:
            return SourceValidation(ok=False, error_code=exc.code, message=exc.message)
        return SourceValidation(ok=True, resolved_name=title or source.name)

    def fetch_posts(
        self, source: SourceRef, since: datetime, until: datetime
    ) -> list[ProviderPost]:
        _, items = self._load(source)
        posts: list[ProviderPost] = []
        for item in items:
            if not item.title:
                continue
            text = item.title
            summary = item.summary
            if (
                source.source_type == "rss"
                and summary
                and not summary.casefold().startswith(item.title.casefold()[:40])
            ):
                text = f"{item.title}\n{_truncate(summary, self._summary_chars)}"
            posts.append(
                ProviderPost(
                    external_post_id=stable_id(item.key),
                    posted_at=item.published,
                    text=text,
                    url=item.link,
                )
            )
        return posts

    def _load(self, source: SourceRef) -> tuple[str | None, list[FeedItem]]:
        if not self.supports(source.source_type):
            raise ProviderError(
                ProviderErrorCode.SOURCE_NOT_SUPPORTED,
                f"Source type {source.source_type!r} is not a feed source.",
            )
        if not source.url:
            raise ProviderError(ProviderErrorCode.INVALID_SOURCE, "Feed source has no source_url.")
        result = self._fetcher.get(source.url, operation=f"feed:{source.identifier}")
        return parse_feed(result.content)

    def close(self) -> None:
        self._fetcher.close()
