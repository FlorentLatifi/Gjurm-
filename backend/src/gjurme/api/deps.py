from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from gjurme.analytics.queries import Range
from gjurme.config import Settings

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]


def local_today(settings: Settings) -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def date_range(
    settings: AppSettings,
    start: Annotated[date | None, Query(alias="from", description="First day (YYYY-MM-DD)")] = None,
    end: Annotated[date | None, Query(alias="to", description="Last day (YYYY-MM-DD)")] = None,
    days: Annotated[
        int | None, Query(ge=1, le=MAX_RANGE_DAYS, description="Window length ending at `to`")
    ] = None,
    source: Annotated[
        list[str] | None, Query(description="Restrict to source slugs", max_length=20)
    ] = None,
) -> Range:
    today = local_today(settings)
    end = end or today
    start = start or end - timedelta(days=(days or DEFAULT_RANGE_DAYS) - 1)
    if start > end:
        raise HTTPException(
            422, detail={"code": "invalid_range", "message": "`from` is after `to`"}
        )
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(
            422, detail={"code": "invalid_range", "message": f"range exceeds {MAX_RANGE_DAYS} days"}
        )
    if end > today + timedelta(days=1):
        raise HTTPException(
            422, detail={"code": "invalid_range", "message": "`to` is in the future"}
        )
    slugs = tuple(sorted(set(source or [])))
    for slug in slugs:
        if not re.match(SLUG_PATTERN, slug):
            raise HTTPException(
                422, detail={"code": "invalid_source", "message": f"invalid source slug: {slug!r}"}
            )
    return Range(start, end, slugs)


DateRangeDep = Annotated[Range, Depends(date_range)]


def cached(request: Request, compute: Callable[[], Any]) -> Any:
    """Serve an analytics result from the in-process TTL cache (keyed by path + query)."""
    key = request.url.path + "?" + "&".join(sorted(request.url.query.split("&")))
    return request.app.state.cache.get_or_set(key, compute)
