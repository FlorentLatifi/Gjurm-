from __future__ import annotations

import pytest

from gjurme.ingestion.feed_parser import discover_feeds, parse_feed, parse_sitemap
from gjurme.ingestion.normalize import is_photo_address
from gjurme.ingestion.processor import _image_url
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


def test_image_from_an_atom_enclosure_with_a_bare_type() -> None:
    atom = b"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<title>k</title><entry><title>B</title><link rel="alternate" href="https://news.example/b"/>
<id>https://news.example/1</id><updated>2026-10-25T18:02:33+01:00</updated>
<link rel="enclosure" href="https://img.example/x.webp?q=80" length="7" type="image"/>
</entry></feed>"""
    assert parse_feed(atom).entries[0]["image"] == "https://img.example/x.webp?q=80"


# Seen on the live site as story photos (2026-11-19): A2 CNN's and Euronews Albania's WordPress
# emoji, Zëri's bare homepage, and an impression pixel of Nacionale's Revive ad server in a
# Lajmi.net entry, which every reader's browser would have requested.
EMOJI = "https://s.w.org/images/core/emoji/17.0.2/72x72/1f5d3.png"
HOMEPAGE = "https://www.zeri.info"
AD_PIXEL = (
    "https://ads.nacionale.com/www/delivery/lg.php?bannerid=483&campaignid=93&zoneid=15"
    "&loc=https%3A%2F%2Fwww.nacionale.com%2Fsq%2Farticles%2Fintervista&cb=d430fa1488"
)
NOT_PHOTOS = [EMOJI, HOMEPAGE, AD_PIXEL]
PHOTOS = [
    "https://telegrafi.com/media-library/image.jpg?id=68722202&width=980",
    "https://resources.koha.net/images/2026/November/19/"
    "c88d9fe8-fb25-472a-8e0b-b98b3d4f4255.webp?q=80",
    "https://ekonomiaonline.com/wp-content/uploads/2026/11/Jakup-Nura-1333x1000.jpg",
]


@pytest.mark.parametrize(
    "url",
    [
        *NOT_PHOTOS,
        "https://www.zeri.info/",
        "https://news.example/wp-includes/images/smilies/icon_smile.gif",
        "https://news.example/blog/wp-includes/images/smilies/frownie.png",
        "https://news.example/revive/www/delivery/avw.php?zoneid=1",
        "https://news.example/www/delivery/ck.png",
        "https://news.example/pixel.PHP",
        "http://cdn.example/a.jpg",
        "https:///a.jpg",
        "https://[cdn.example/a.jpg",  # not even an address: urlsplit refuses it
        "not an address",
    ],
)
def test_addresses_that_are_no_photo(url: str) -> None:
    assert not is_photo_address(url)
    assert _image_url(url) is None  # nor taken from a payload parsed before the rule


@pytest.mark.parametrize("url", PHOTOS)
def test_real_photos_are_photo_addresses(url: str) -> None:
    assert is_photo_address(url)
    assert _image_url(url) == url


def _html_image(html: str) -> str | None:
    image = parse_feed(_feed(f"<description><![CDATA[{html}]]></description>")).entries[0]
    return image["image"]  # type: ignore[no-any-return]


@pytest.mark.parametrize("url", NOT_PHOTOS)
def test_an_entry_whose_only_image_is_no_photo_has_none(url: str) -> None:
    assert _html_image(f'<p><img src="{url}" alt=""> Tekst</p>') is None
    assert parse_feed(_feed(f'<media:thumbnail url="{url}"/>')).entries[0]["image"] is None
    content = parse_feed(_feed(f'<media:content url="{url}" medium="image"/>'))
    assert content.entries[0]["image"] is None
    enclosure = parse_feed(_feed(f'<enclosure url="{url}" type="image/png" length="1"/>'))
    assert enclosure.entries[0]["image"] is None


@pytest.mark.parametrize("photo", PHOTOS)
def test_the_first_img_that_is_a_photo_is_taken(photo: str) -> None:
    html = (
        f'<p><img draggable="false" role="img" class="emoji" alt="🗓" src="{EMOJI}"> Lajm</p>'
        f'<img src="{AD_PIXEL.replace("&", "&amp;")}" width="0" height="0" alt="">'
        f'<img src="{HOMEPAGE}"><img src="{photo.replace("&", "&amp;")}" alt="Foto">'
    )
    assert _html_image(html) == photo
    assert parse_feed(_feed(f'<media:thumbnail url="{photo}"/>')).entries[0]["image"] == photo


def test_emoji_and_pixels_are_known_by_the_tag_too() -> None:
    photo = "https://news.example/uploads/foto.jpg"
    # a WordPress smiley served from the outlet's own host, under any address
    smiley = '<img class="wp-smiley" style="height: 1em" src="https://news.example/s/1f600.png">'
    assert _html_image(f'{smiley}<img src="{photo}">') == photo
    # a 1 px image declared in the tag: a tracking pixel, wherever it is served from
    for size in ('width="1" height="1"', 'width="2px"', 'height="1"'):
        pixel = f'<img src="https://stats.example/t.gif?id=9" {size}>'
        assert _html_image(f'{pixel}<img src="{photo}" width="980">') == photo
    # declared sizes above 2 px, or not in pixels, are photos
    assert _html_image(f'<img src="{photo}" width="3" height="100%">') == photo


def test_a_sitemap_photo_that_is_the_homepage_is_none() -> None:
    sitemap = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url><loc>https://lajme.example.com/a</loc>
    <news:news><news:title>Lajmi i dit\xc3\xabs</news:title></news:news>
    <image:image><image:loc>https://lajme.example.com/</image:loc></image:image>
  </url>
</urlset>"""
    feed = parse_sitemap(sitemap)
    assert feed is not None and feed.entries[0]["image"] is None
