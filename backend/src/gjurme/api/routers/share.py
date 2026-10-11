"""Link previews for shared story links.

The site is a single-page app: every URL returns the same index.html, so a story link pasted into
Facebook, WhatsApp, X, Telegram or Slack would preview as the home page. The edge (Caddy) sends
link-preview crawlers — and only them — here instead; readers and search engines get the app.
The page carries the story's own title and description, and sends anyone who opens it to the real
story page. Metadata only, never article text (ADR-003); every value is HTML-escaped.
"""

from __future__ import annotations

from html import escape
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from fastapi.responses import HTMLResponse

from gjurme.analytics import stories as st
from gjurme.api.deps import DB, AppSettings, cached

share_router = APIRouter(prefix="/api/share", include_in_schema=False)

CACHE = "public, max-age=300"
SITE_DESCRIPTION = (
    "Albanian-language news grouped into stories, with which outlets covered each one."
)


def _description(story: dict[str, Any]) -> str:
    summary = story.get("summary_en") or ""
    # keyword-rule analysis stores a placeholder ("[headline, no AI summary] …"), not a summary
    lead = summary if summary and not summary.startswith("[headline") else ""
    names = [s["name"] for s in story["sources"]]
    shown = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
    count = story["source_count"]
    outlets = f"{count} outlet{'s' if count != 1 else ''}"
    coverage = f"{outlets} covered this story: {shown}." if count > 1 else f"Reported by {shown}."
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
            title="GJURMË — see every side of the story",
            description=SITE_DESCRIPTION,
            url=f"{base}/",
            image=image,
            lang="en",
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
