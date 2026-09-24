from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta
from time import strptime

import pytest

from gjurme.ingestion.normalize import (
    InvalidURLError,
    canonical_url,
    clean_excerpt,
    clean_text,
    fix_mojibake,
    fold,
    item_key,
    normalize_key,
    normalize_url,
    parse_feed_datetime,
    resolve_published_at,
    truncate,
    url_hash,
    validate_public_http_url,
)


class TestText:
    def test_strips_html_and_unescapes_entities(self) -> None:
        raw = "<p>Deputetët miratuan &#8220;buxhetin&#8221; &amp; ligjin</p>"
        assert clean_text(raw) == "Deputetët miratuan “buxhetin” & ligjin"

    def test_double_escaped_entities(self) -> None:
        assert clean_text("Kosov&amp;euml;") == "Kosovë"

    def test_normalizes_to_nfc(self) -> None:
        decomposed = "Kosovë"  # e + combining diaeresis
        assert clean_text(decomposed) == "Kosovë"
        assert unicodedata.is_normalized("NFC", clean_text(decomposed))

    def test_preserves_albanian_letters(self) -> None:
        assert clean_text("Çështja e Shqipërisë") == "Çështja e Shqipërisë"

    def test_removes_zero_width_and_collapses_whitespace(self) -> None:
        assert clean_text("  Lajm​ i\n\n fundit﻿ ") == "Lajm i fundit"

    def test_none_is_empty(self) -> None:
        assert clean_text(None) == ""

    def test_mojibake_repaired(self) -> None:
        assert fix_mojibake("KosovÃ« dhe Ã§mimet") == "Kosovë dhe çmimet"

    def test_mojibake_leaves_clean_text_alone(self) -> None:
        assert fix_mojibake("Kosovë dhe çmimet") == "Kosovë dhe çmimet"

    def test_excerpt_drops_wordpress_footer_and_ellipsis(self) -> None:
        raw = "Teksti kryesor i lajmit. The post Titulli appeared first on Portali. "
        assert clean_excerpt(raw, 500) == "Teksti kryesor i lajmit."
        assert clean_excerpt("Diçka ndodhi […]", 500) == "Diçka ndodhi"

    def test_truncate_on_word_boundary(self) -> None:
        text = "fjala " * 50
        out = truncate(text.strip(), 40)
        assert len(out) <= 40
        assert out.endswith("…")
        assert not out.endswith(" …")


class TestKeys:
    def test_fold_removes_diacritics_and_case(self) -> None:
        assert fold("SHQIPËRIA çka") == "shqiperia cka"

    def test_normalize_key(self) -> None:
        assert normalize_key("  Kuvendi i Kosovës: “Buxheti”! ") == "kuvendi i kosoves buxheti"

    def test_item_key_prefers_guid(self) -> None:
        a = item_key("guid-1", "https://x.example.com/a", "T", None)
        b = item_key("guid-1", "https://x.example.com/b", "Other", None)
        assert a == b

    def test_item_key_falls_back_to_canonical_link(self) -> None:
        a = item_key(None, "https://www.x.example.com/a/?utm_source=rss", "T", None)
        b = item_key(None, "http://x.example.com/a", "T2", None)
        assert a == b


class TestUrls:
    def test_normalize_removes_tracking_and_fragment(self) -> None:
        url = "HTTPS://Portali.Example.com//lajme/a/?utm_source=rss&id=5&fbclid=xyz#comments"
        assert normalize_url(url) == "https://portali.example.com/lajme/a/?id=5"

    def test_relative_url_resolved_against_base(self) -> None:
        assert (
            normalize_url("/lajme/1", base="https://p.example.com/")
            == "https://p.example.com/lajme/1"
        )

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("http://www.p.example.com/a/", "https://p.example.com/a"),
            ("https://p.example.com/a/amp/", "https://p.example.com/a"),
            ("https://p.example.com/a?b=2&a=1", "https://p.example.com/a?a=1&b=2"),
            ("https://p.example.com:443/a", "https://p.example.com/a"),
        ],
    )
    def test_canonical_equivalences(self, a: str, b: str) -> None:
        assert canonical_url(a) == canonical_url(b)
        assert url_hash(a) == url_hash(b)

    def test_canonical_keeps_meaningful_query(self) -> None:
        assert canonical_url("https://p.example.com/?p=101") != canonical_url(
            "https://p.example.com/?p=102"
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "javascript:alert(1)",
            "data:text/html,<script>",
            "ftp://p.example.com/file",
            "https://user:pass@p.example.com/",
            "http://127.0.0.1/admin",
            "http://10.0.0.5/",
            "http://[::1]/",
            "http://localhost:5432/",
            "http://db.internal/",
            "https:///nohost",
            "",
        ],
    )
    def test_rejects_unsafe_urls(self, bad: str) -> None:
        with pytest.raises(InvalidURLError):
            normalize_url(bad)

    def test_validate_accepts_public_url(self) -> None:
        assert (
            validate_public_http_url(" https://telegrafi.com/feed/ ")
            == "https://telegrafi.com/feed/"
        )

    def test_idn_host(self) -> None:
        assert normalize_url("https://zëri.example/lajm").startswith("https://xn--")


class TestDates:
    def test_struct_time_is_utc(self) -> None:
        st = strptime("2026-09-24 09:30:00", "%Y-%m-%d %H:%M:%S")
        assert parse_feed_datetime({"published_parsed": st}) == datetime(
            2026, 9, 24, 9, 30, tzinfo=UTC
        )

    def test_rfc822_with_offset_converted_to_utc(self) -> None:
        dt = parse_feed_datetime({"published": "Wed, 24 Sep 2026 11:15:00 +0200"})
        assert dt == datetime(2026, 9, 24, 9, 15, tzinfo=UTC)

    def test_iso8601(self) -> None:
        dt = parse_feed_datetime({"updated": "2026-09-24T07:30:00+02:00"})
        assert dt == datetime(2026, 9, 24, 5, 30, tzinfo=UTC)

    def test_garbage_date(self) -> None:
        assert parse_feed_datetime({"published": "dje në mbrëmje"}) is None

    def test_resolve_missing(self) -> None:
        seen = datetime(2026, 9, 24, 12, tzinfo=UTC)
        assert resolve_published_at(None, seen) == (seen, True, "missing_date")

    def test_resolve_future_is_clamped(self) -> None:
        seen = datetime(2026, 9, 24, 12, tzinfo=UTC)
        dt, est, issue = resolve_published_at(seen + timedelta(hours=2), seen)
        assert (dt, est, issue) == (seen, True, "future_date")

    def test_resolve_small_clock_skew_is_accepted(self) -> None:
        seen = datetime(2026, 9, 24, 12, tzinfo=UTC)
        dt, est, _ = resolve_published_at(seen + timedelta(minutes=5), seen)
        assert not est and dt == seen + timedelta(minutes=5)

    def test_resolve_implausible(self) -> None:
        seen = datetime(2026, 9, 24, 12, tzinfo=UTC)
        _, est, issue = resolve_published_at(datetime(1970, 1, 1, tzinfo=UTC), seen)
        assert est and issue == "implausible_date"


class TestNearVerbatim:
    """Pairs measured in ADR-008: place-name variants are *different* events."""

    @pytest.mark.parametrize(
        ("a", "b", "same"),
        [
            ("rriten cmimet e ushqimeve ne prizren", "rriten cmimet e ushqimeve ne peje", False),
            (
                "zjarr ne nje ndertese banimi ne prizren",
                "zjarr ne nje ndertese banimi ne peje",
                False,
            ),
            ("arrestohen 3 persona per kontrabande", "arrestohen 4 persona per kontrabande", False),
            ("video kurti takon ambasadorin amerikan", "kurti takon ambasadorin amerikan", True),
            ("qeveria miraton ligjin e ri", "qeveria miraton ligjin e ri", True),
            ("qeveria miraton ligjin e ri", "qeveria miraton ligjin i ri", True),
        ],
    )
    def test_is_near_verbatim(self, a: str, b: str, same: bool) -> None:
        from gjurme.ingestion.processor import is_near_verbatim

        assert is_near_verbatim(a, b) is same
