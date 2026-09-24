from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from sqlalchemy.orm import Session

from gjurme.db.models import Source


def add_source(
    session: Session,
    slug: str,
    feed_url: str | None = None,
    homepage: str | None = None,
    active: bool = True,
) -> Source:
    homepage = homepage or f"https://{slug}.example.com/"
    src = Source(
        slug=slug,
        name=slug.title(),
        homepage_url=homepage,
        feed_url=feed_url or f"{homepage}feed/",
        language="sq",
        country="XK",
        is_active=active,
    )
    session.add(src)
    session.flush()
    return src


def rss(items: list[dict[str, str]], title: str = "Feed") -> bytes:
    """Minimal RSS 2.0 document; each item dict may have title/link/guid/pubDate/description."""
    parts = [
        f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{title}</title>'
    ]
    for it in items:
        parts.append("<item>")
        for tag in ("title", "link", "guid", "pubDate", "description"):
            if it.get(tag) is not None:
                parts.append(f"<{tag}><![CDATA[{it[tag]}]]></{tag}>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    return "".join(parts).encode("utf-8")


def pubdate(hours_ago: float = 1.0) -> str:
    return format_datetime(datetime.now(UTC) - timedelta(hours=hours_ago))
