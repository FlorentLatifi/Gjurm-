"""News sitemaps read as feeds: Google News (Klan Kosova, KosovaPress) and PageMap (A2 CNN)."""

from __future__ import annotations

from datetime import UTC, datetime

from gjurme.ingestion.feed_parser import parse_feed, parse_sitemap
from gjurme.ingestion.fetcher import dated_url

GOOGLE_NEWS = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url>
    <loc>https://lajme.example.com/kuvendi-miraton-buxhetin</loc>
    <news:news>
      <news:publication><news:name>Lajme</news:name><news:language>sq</news:language></news:publication>
      <news:publication_date>2026-11-18T20:24:13.750Z</news:publication_date>
      <news:title>Kuvendi miraton buxhetin &amp; ligjin p\xc3\xabr pagat</news:title>
    </news:news>
    <image:image><image:loc>https://lajme.example.com/foto.jpg</image:loc></image:image>
  </url>
  <url>
    <loc>https://lajme.example.com/pa-titull</loc>
    <lastmod>2026-11-18T20:00:00Z</lastmod>
  </url>
</urlset>"""

PAGEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:pagemap="http://www.google.com/schemas/sitemap-pagemap/1.0">
  <url>
    <loc>https://tv.example.al/aksident-ne-voskopoje-i1188250</loc>
    <pagemap:PageMap>
      <pagemap:DataObject type="article">
        <pagemap:Attribute name="publication_date">2026-11-01T08:46:31+01:00</pagemap:Attribute>
        <pagemap:Attribute name="headline">Aksident n\xc3\xab Voskopoj\xc3\xab</pagemap:Attribute>
      </pagemap:DataObject>
    </pagemap:PageMap>
  </url>
</urlset>"""

PLAIN_SITEMAP = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc><lastmod>2026-11-18</lastmod></url>
</urlset>"""


def test_a_google_news_sitemap_is_a_feed_of_headlines() -> None:
    feed = parse_feed(GOOGLE_NEWS)
    assert feed.is_feed and feed.title == "Lajme"
    [entry] = feed.entries  # a URL without a headline is no article for us
    assert entry["title"] == "Kuvendi miraton buxhetin & ligjin për pagat"
    assert entry["link"] == entry["id"] == "https://lajme.example.com/kuvendi-miraton-buxhetin"
    assert entry["published_iso"] == "2026-11-18T20:24:13.750000+00:00"
    assert entry["image"] == "https://lajme.example.com/foto.jpg"
    assert entry["summary"] is None and entry["language"] == "sq"


def test_a_pagemap_sitemap_is_read_too() -> None:
    [entry] = parse_feed(PAGEMAP).entries
    assert entry["title"] == "Aksident në Voskopojë"
    assert entry["published_iso"] == "2026-11-01T07:46:31+00:00"


def test_a_sitemap_without_headlines_is_not_a_feed() -> None:
    assert parse_sitemap(PLAIN_SITEMAP) is None
    assert parse_sitemap(b"<rss><channel></channel></rss>") is None
    assert not parse_feed(PLAIN_SITEMAP).entries


def test_a_monthly_sitemap_address_is_filled_in() -> None:
    url = "https://tv.example.al/sitemaps/sitemap-{year}-{month}.xml"
    assert dated_url(url, datetime(2026, 1, 5, tzinfo=UTC)).endswith("sitemap-2026-01.xml")
    assert dated_url("https://example.com/feed/") == "https://example.com/feed/"
