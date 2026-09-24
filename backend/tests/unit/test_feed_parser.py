from __future__ import annotations

from gjurme.ingestion.feed_parser import discover_feeds, parse_feed
from tests.conftest import fixture_bytes


def test_wordpress_feed_fields_and_unicode() -> None:
    parsed = parse_feed(fixture_bytes("wordpress_sq.xml"))
    assert parsed.is_feed and not parsed.malformed
    assert parsed.language == "sq"
    assert len(parsed.entries) == 3
    first = parsed.entries[0]
    assert first["title"] == "Kuvendi i Kosovës miraton buxhetin për vitin 2027"
    assert first["id"] == "https://portali.example.com/?p=101"
    assert first["tags"] == ["Politikë", "Lajme"]
    assert first["author"] == "Redaksia"
    assert first["published_iso"] == "2026-09-24T09:30:00+00:00"
    # content:encoded is measured but never stored
    assert first["content_length"] and "Full article" not in str(first)


def test_pubdate_offset_normalized_to_utc() -> None:
    parsed = parse_feed(fixture_bytes("wordpress_sq.xml"))
    assert parsed.entries[1]["published_iso"] == "2026-09-24T09:15:00+00:00"
    assert parsed.entries[1]["author"] == "Arta Çollaku"


def test_atom_feed() -> None:
    parsed = parse_feed(fixture_bytes("atom.xml"))
    assert parsed.is_feed and len(parsed.entries) == 2
    assert parsed.entries[0]["link"] == "https://regional.example.org/2026/09/24/dialogue-brussels/"
    assert parsed.entries[0]["published_iso"] == "2026-09-24T05:30:00+00:00"


def test_malformed_feed_still_yields_entries_and_is_flagged() -> None:
    parsed = parse_feed(fixture_bytes("malformed.xml"))
    assert parsed.malformed
    assert parsed.malformed_reason
    assert len(parsed.entries) >= 1


def test_html_page_is_not_a_feed() -> None:
    parsed = parse_feed(fixture_bytes("not_a_feed.html"))
    assert not parsed.is_feed
    assert parsed.entries == []


def test_empty_feed_is_feed_without_entries() -> None:
    parsed = parse_feed(fixture_bytes("empty.xml"))
    assert parsed.is_feed and parsed.entries == []


def test_feed_autodiscovery() -> None:
    found = discover_feeds(fixture_bytes("not_a_feed.html"), "https://portali.example.com/")
    urls = {f["url"] for f in found}
    assert "https://portali.example.com/feed/" in urls
    assert "https://portali.example.com/atom.xml" in urls
    assert "https://portali.example.com/rss/lajme" in urls
    assert "https://portali.example.com/kontakt" not in urls
