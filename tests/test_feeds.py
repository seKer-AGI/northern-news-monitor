"""Feed provider + HTTP fetcher tests (httpx.MockTransport — no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.providers.base import ProviderError, ProviderErrorCode, SourceRef
from app.providers.feeds import FeedProvider, parse_feed, parse_feed_datetime
from app.providers.http_fetch import HttpFetcher
from app.providers.retry import RetryPolicy

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>Dawn - Pakistan</title>
  <item>
    <title>Heavy snowfall cuts off Babusar Top</title>
    <link>https://www.dawn.com/news/1/snowfall</link>
    <guid>https://www.dawn.com/news/1</guid>
    <pubDate>Tue, 15 Sep 2026 11:49:52 +0500</pubDate>
    <description><![CDATA[<p>Traffic on the <b>Babusar</b> road was suspended &amp; tourists moved.</p>]]></description>
  </item>
  <item>
    <title>Geo style date</title>
    <link>https://www.geo.tv/latest/2</link>
    <pubDate>Tue, 15 Sep 2026 18:28:00 +05:00</pubDate>
  </item>
  <item>
    <title>ARY style date</title>
    <link>https://arynews.tv/3</link>
    <pubDate>2026-09-15T19:34:41+05:00</pubDate>
  </item>
  <item>
    <title>Naive date</title>
    <link>https://example.pk/4</link>
    <pubDate>2026-09-15 10:00:00</pubDate>
  </item>
</channel>
</rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <id>tag:example,2026:1</id>
    <title>Avalanche warning for Hunza</title>
    <link rel="alternate" href="https://example.org/hunza"/>
    <updated>2026-09-15T06:00:00Z</updated>
    <summary>PDMA warns of avalanche risk.</summary>
  </entry>
</feed>"""


def _fetcher(handler, sleeps=None, max_bytes=1_000_000, retries=2):
    return HttpFetcher(
        user_agent="test-agent",
        timeout=5,
        retry=RetryPolicy(max_retries=retries, base_delay=0, max_delay=0),
        max_bytes=max_bytes,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(sleeps.append if sleeps is not None else lambda _s: None),
    )


def _xml(body: str, status: int = 200):
    return lambda request: httpx.Response(status, content=body.encode("utf-8"))


def test_parse_rss_dates_and_summary():
    title, items = parse_feed(RSS.encode())
    assert title == "Dawn - Pakistan"
    assert len(items) == 4
    first = items[0]
    assert first.key == "https://www.dawn.com/news/1"
    assert first.link == "https://www.dawn.com/news/1/snowfall"
    assert first.published == datetime(2026, 9, 15, 6, 49, 52, tzinfo=UTC)
    assert first.summary == "Traffic on the Babusar road was suspended & tourists moved."
    assert items[1].published == datetime(2026, 9, 15, 13, 28, tzinfo=UTC)
    assert items[2].published == datetime(2026, 9, 15, 14, 34, 41, tzinfo=UTC)
    assert items[3].published == datetime(2026, 9, 15, 5, 0, tzinfo=UTC)  # naive → PKT


def test_parse_atom():
    title, items = parse_feed(ATOM.encode())
    assert title == "Atom Feed"
    assert items[0].link == "https://example.org/hunza"
    assert items[0].published == datetime(2026, 9, 15, 6, 0, tzinfo=UTC)
    assert items[0].summary == "PDMA warns of avalanche risk."


@pytest.mark.parametrize("value", [None, "", "not a date"])
def test_unparseable_dates_return_none(value):
    assert parse_feed_datetime(value) is None


def test_rss_source_posts_include_summary_url_and_stable_ids():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, content=RSS.encode())

    provider = FeedProvider(_fetcher(handler))
    ref = SourceRef("rss", "dawn", "Dawn", "https://www.dawn.com/feeds/pakistan")
    first = provider.fetch_posts(ref, NOW - timedelta(days=1), NOW)
    second = provider.fetch_posts(ref, NOW - timedelta(days=1), NOW)

    assert [p.external_post_id for p in first] == [p.external_post_id for p in second]
    assert len(first[0].external_post_id) == 40
    assert first[0].text == (
        "Heavy snowfall cuts off Babusar Top\n"
        "Traffic on the Babusar road was suspended & tourists moved."
    )
    assert first[0].url == "https://www.dawn.com/news/1/snowfall"
    assert seen["ua"] == "test-agent"


def test_google_news_uses_headline_only():
    gn = RSS.replace("<description>", "<description>&lt;a href='x'&gt;link list&lt;/a&gt;")
    provider = FeedProvider(_fetcher(_xml(gn)))
    ref = SourceRef("google_news", "gn", "GN", "https://news.google.com/rss/search?q=x")
    posts = provider.fetch_posts(ref, NOW - timedelta(days=1), NOW)
    assert posts[0].text == "Heavy snowfall cuts off Babusar Top"


def test_validate_source_returns_channel_title():
    provider = FeedProvider(_fetcher(_xml(RSS)))
    result = provider.validate_source(SourceRef("rss", "dawn", "Dawn", "https://x.test/feed"))
    assert result.ok and result.resolved_name == "Dawn - Pakistan"


def test_invalid_xml_is_provider_error():
    provider = FeedProvider(_fetcher(_xml("<html>not a feed</html")))
    with pytest.raises(ProviderError) as exc:
        provider.fetch_posts(SourceRef("rss", "x", "X", "https://x.test/feed"), NOW, NOW)
    assert exc.value.code == ProviderErrorCode.PROVIDER_ERROR


def test_xml_entity_expansion_is_rejected():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>'
        "<rss><channel><item><title>&lol2;</title></item></channel></rss>"
    )
    with pytest.raises(ProviderError):
        parse_feed(bomb.encode())


def test_forbidden_is_not_retried_or_bypassed():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403)

    sleeps: list[float] = []
    provider = FeedProvider(_fetcher(handler, sleeps))
    with pytest.raises(ProviderError) as exc:
        provider.fetch_posts(SourceRef("rss", "x", "X", "https://x.test/feed"), NOW, NOW)
    assert exc.value.code == ProviderErrorCode.PERMISSION_DENIED
    assert len(calls) == 1 and sleeps == []


def test_transient_errors_are_retried():
    responses = iter([httpx.Response(503), httpx.Response(200, content=RSS.encode())])
    sleeps: list[float] = []
    provider = FeedProvider(_fetcher(lambda r: next(responses), sleeps))
    posts = provider.fetch_posts(SourceRef("rss", "x", "X", "https://x.test/feed"), NOW, NOW)
    assert len(posts) == 4 and len(sleeps) == 1


def test_not_found_maps_to_invalid_source():
    provider = FeedProvider(_fetcher(_xml("", status=404)))
    result = provider.validate_source(SourceRef("rss", "x", "X", "https://x.test/feed"))
    assert not result.ok and result.error_code == ProviderErrorCode.INVALID_SOURCE


def test_oversized_response_is_rejected():
    provider = FeedProvider(_fetcher(_xml(RSS), max_bytes=100))
    with pytest.raises(ProviderError) as exc:
        provider.fetch_posts(SourceRef("rss", "x", "X", "https://x.test/feed"), NOW, NOW)
    assert "larger than" in exc.value.message


@pytest.mark.parametrize("url", [None, "ftp://x.test/feed", "file:///etc/passwd"])
def test_missing_or_non_http_url_is_invalid(url):
    provider = FeedProvider(_fetcher(_xml(RSS)))
    with pytest.raises(ProviderError) as exc:
        provider.fetch_posts(SourceRef("rss", "x", "X", url), NOW, NOW)
    assert exc.value.code == ProviderErrorCode.INVALID_SOURCE


def test_timeout_maps_to_unavailable():
    def handler(request):
        raise httpx.ConnectTimeout("slow", request=request)

    provider = FeedProvider(_fetcher(handler, retries=0))
    with pytest.raises(ProviderError) as exc:
        provider.fetch_posts(SourceRef("rss", "x", "X", "https://x.test/feed"), NOW, NOW)
    assert exc.value.code == ProviderErrorCode.PROVIDER_UNAVAILABLE
