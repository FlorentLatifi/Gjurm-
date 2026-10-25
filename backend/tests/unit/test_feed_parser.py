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


def _feed(item: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>T</title><link>https://news.example/</link>
<item><title>Lajm</title><link>https://news.example/a/1</link>{item}</item>
</channel></rss>""".encode()


def test_image_from_media_content_first() -> None:
    parsed = parse_feed(
        _feed(
            '<media:content url="https://cdn.example/a.jpg" medium="image"/>'
            '<media:thumbnail url="https://cdn.example/thumb.jpg"/>'
        )
    )
    assert parsed.entries[0]["image"] == "https://cdn.example/a.jpg"


def test_image_from_thumbnail_and_enclosure() -> None:
    thumb = parse_feed(_feed('<media:thumbnail url="https://cdn.example/t.jpg"/>'))
    assert thumb.entries[0]["image"] == "https://cdn.example/t.jpg"
    enclosure = parse_feed(
        _feed('<enclosure url="https://cdn.example/e.png" type="image/png" length="1"/>')
    )
    assert enclosure.entries[0]["image"] == "https://cdn.example/e.png"
    audio = parse_feed(
        _feed('<enclosure url="https://cdn.example/e.mp3" type="audio/mpeg" length="1"/>')
    )
    assert audio.entries[0]["image"] is None


def test_image_from_entry_html_is_resolved_and_upgraded() -> None:
    relative = parse_feed(
        _feed('<description><![CDATA[<p><img src="/img/x.webp"> Tekst</p>]]></description>')
    )
    assert relative.entries[0]["image"] == "https://news.example/img/x.webp"
    plain = parse_feed(
        _feed(
            '<content:encoded><![CDATA[<img src="http://news.example/y.jpg">]]></content:encoded>'
        )
    )
    assert plain.entries[0]["image"] == "https://news.example/y.jpg"


def test_no_unsafe_or_missing_image() -> None:
    assert parse_feed(_feed("<description>Tekst</description>")).entries[0]["image"] is None
    unsafe = parse_feed(
        _feed('<description><![CDATA[<img src="javascript:alert(1)">]]></description>')
    )
    assert unsafe.entries[0]["image"] is None
    data = parse_feed(_feed('<media:thumbnail url="data:image/png;base64,AAAA"/>'))
    assert data.entries[0]["image"] is None
