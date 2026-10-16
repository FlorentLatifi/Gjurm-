"""Link previews for shared story links, and the sitemap.

The site is a single-page app: every URL returns the same index.html, so a story link pasted into
Facebook, WhatsApp, X, Telegram or Slack would preview as the home page. The edge (Caddy) sends
link-preview crawlers — and only them — here instead; readers and search engines get the app.
The page carries the story's own title and description, and sends anyone who opens it to the real
story page. Metadata only, never article text (ADR-003); every value is HTML-escaped.

The sitemap (``/sitemap.xml`` at the edge) lists the site's pages, the outlets, the topics and
the stories of the last ``SITEMAP_DAYS`` that more than one outlet covered: the pages search
engines cannot find by following links, since the feed pages with buttons, not links.
"""

from __future__ import annotations

from datetime import timedelta
from html import escape
from typing import Annotated, Any
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Path, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from gjurme.analytics import stories as st
from gjurme.api.deps import DB, AppSettings, cached, local_today
from gjurme.config import Settings

share_router = APIRouter(prefix="/api/share", include_in_schema=False)

CACHE = "public, max-age=300"
# Previews speak the site's language: Albanian, like the headlines they show.
SITE_TITLE = "GJURMË — shih çdo anë të lajmit"
SITE_DESCRIPTION = "Lajmet në shqip të grupuara sipas ngjarjeve, me mediat që raportuan secilën."


def _description(story: dict[str, Any]) -> str:
    # The Albanian AI summary leads when there is one (prompt v1.2+); the English one never
    # appears in an Albanian preview. Keyword rules store a placeholder, not a summary.
    summary = story.get("summary_sq") or ""
    lead = summary if summary and not summary.startswith("[headline") else ""
    names = [s["name"] for s in story["sources"]]
    shown = ", ".join(names[:4]) + (f" dhe {len(names) - 4} të tjera" if len(names) > 4 else "")
    count = story["source_count"]
    coverage = (
        f"{count} media e raportuan këtë lajm: {shown}." if count > 1 else f"Raportuar nga {shown}."
    )
    return f"{lead} {coverage}".strip()


def _page(
    *, title: str, description: str, url: str, image: str, lang: str, status: int
) -> HTMLResponse:
    t, d, u, i = (escape(v, quote=True) for v in (title, description, url, image))
    html = f"""<!doctype html>
<html lang="{escape(lang, quote=True)}">
<head>
<meta charset="utf-8">
<title>{t}</title>
<meta name="description" content="{d}">
<link rel="canonical" href="{u}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="GJURMË">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:url" content="{u}">
<meta property="og:image" content="{i}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0; url={u}">
</head>
<body><p><a href="{u}">{t}</a></p></body>
</html>
"""
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": CACHE})


@share_router.get("/stories/{story_id}", response_class=HTMLResponse)
def story_preview(
    request: Request, db: DB, settings: AppSettings, story_id: Annotated[int, Path(ge=1)]
) -> HTMLResponse:
    base = settings.public_base_url.rstrip("/")
    image = f"{base}/og-image.png"
    story = cached(request, lambda: st.story_detail(db, story_id))
    if story is None:
        return _page(
            title=SITE_TITLE,
            description=SITE_DESCRIPTION,
            url=f"{base}/",
            image=image,
            lang="sq",
            status=404,
        )
    return _page(
        title=f"{story['title']} · GJURMË",
        description=_description(story),
        url=f"{base}/stories/{story_id}",
        image=image,
        lang=story.get("language") or "sq",
        status=200,
    )


SITEMAP_DAYS = 90
SITEMAP_MAX_STORIES = 45_000  # the protocol allows 50,000 URLs per file
SITEMAP_TTL_SECONDS = 3600
# The app's own pages (the router's static routes; per-item pages are listed from the data).
SITE_PAGES = (
    "/",
    "/blindspot",
    "/dashboard",
    "/trends",
    "/topics",
    "/entities",
    "/sources",
    "/articles",
    "/about",
)


@share_router.get("/sitemap.xml")
def sitemap(request: Request, db: DB, settings: AppSettings) -> Response:
    xml = request.app.state.cache.get_or_set(
        "sitemap", lambda: _sitemap(db, settings), ttl=SITEMAP_TTL_SECONDS
    )
    return Response(
        xml,
        media_type="application/xml",
        headers={"Cache-Control": f"public, max-age={SITEMAP_TTL_SECONDS}"},
    )


def _sitemap(db: Session, settings: Settings) -> str:
    base = settings.public_base_url.rstrip("/")
    since = local_today(settings) - timedelta(days=SITEMAP_DAYS)
    urls: list[tuple[str, str | None]] = [(path, None) for path in SITE_PAGES]
    stories = db.execute(
        text("""
        SELECT a.story_id, max(a.published_at) AS last_at
        FROM core.articles a JOIN core.stories st ON st.id = a.story_id
        WHERE st.published_date >= :since AND a.published_date >= :since AND NOT a.is_hidden
        GROUP BY a.story_id HAVING count(DISTINCT a.source_id) >= 2
        ORDER BY last_at DESC LIMIT :limit
    """),
        {"since": since, "limit": SITEMAP_MAX_STORIES},
    )
    urls += [(f"/stories/{r.story_id}", r.last_at.date().isoformat()) for r in stories]
    sources = db.scalars(
        text("""
        SELECT slug FROM core.sources s
        WHERE s.is_active OR EXISTS (SELECT 1 FROM core.articles a WHERE a.source_id = s.id)
        ORDER BY slug
    """)
    )
    urls += [(f"/sources/{slug}", None) for slug in sources]
    topics = db.scalars(text("SELECT slug FROM core.topics ORDER BY sort_order, slug"))
    urls += [(f"/topics/{slug}", None) for slug in topics]
    entries = "\n".join(
        f"  <url><loc>{xml_escape(base + path)}</loc>"
        + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "")
        + "</url>"
        for path, lastmod in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n</urlset>\n"
    )
