"""Public read-only endpoints: analytics, topics, entities, sources, articles."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request
from sqlalchemy import text

from gjurme.analytics import queries as q
from gjurme.api.deps import DB, AppSettings, DateRangeDep, cached, local_today
from gjurme.api.schemas import (
    ArticleDetail,
    ArticleSummary,
    CoOccurrence,
    EntityDetail,
    EntitySpikes,
    EntityStat,
    ErrorResponse,
    GroupedVolumeSeries,
    Overview,
    Page,
    SentimentGroups,
    SentimentSeries,
    SentimentShift,
    SourceStat,
    TaxonomyTopic,
    TopicDetail,
    TopicMomentum,
    TopicStat,
    VolumeSeries,
)

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
router = APIRouter(
    prefix="/api/v1", responses={422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}}
)

GroupBy = Literal["source", "topic"]


# ------------------------------------------------------------------------------------------
# Analytics
# ------------------------------------------------------------------------------------------
@router.get(
    "/analytics/overview",
    response_model=Overview,
    tags=["analytics"],
    summary="Headline numbers for the selected period",
)
def analytics_overview(request: Request, db: DB, settings: AppSettings, rng: DateRangeDep) -> Any:
    today = local_today(settings)
    return cached(request, lambda: q.overview(db, rng, today))


@router.get(
    "/analytics/volume",
    response_model=VolumeSeries | GroupedVolumeSeries,
    tags=["analytics"],
    summary="Daily article volume (optionally per source/topic)",
)
def analytics_volume(
    request: Request, db: DB, rng: DateRangeDep, group_by: GroupBy | None = None
) -> Any:
    return cached(request, lambda: q.volume(db, rng, group_by))


@router.get(
    "/analytics/sentiment",
    response_model=SentimentSeries | SentimentGroups,
    tags=["analytics"],
    summary="Sentiment over time, or compared across sources/topics",
)
def analytics_sentiment(
    request: Request, db: DB, rng: DateRangeDep, group_by: GroupBy | None = None
) -> Any:
    return cached(request, lambda: q.sentiment_series(db, rng, group_by))


@router.get(
    "/analytics/sentiment/shift",
    response_model=SentimentShift,
    tags=["analytics"],
    summary="Topics whose tone changed most week over week",
)
def analytics_sentiment_shift(
    request: Request, db: DB, settings: AppSettings, window: Annotated[int, Query(ge=3, le=30)] = 7
) -> Any:
    today = local_today(settings)
    return cached(request, lambda: q.sentiment_shift(db, today, window=window))


@router.get(
    "/analytics/trends/topics",
    response_model=TopicMomentum,
    tags=["analytics"],
    summary="Accelerating topics (period-over-period growth)",
)
def trends_topics(
    request: Request, db: DB, settings: AppSettings, window: Annotated[int, Query(ge=3, le=30)] = 7
) -> Any:
    today = local_today(settings)
    return cached(request, lambda: q.topic_momentum(db, today, window=window))


@router.get(
    "/analytics/trends/entities",
    response_model=EntitySpikes,
    tags=["analytics"],
    summary="Entities with unusual mention spikes in the last 24 hours",
)
def trends_entities(
    request: Request, db: DB, limit: Annotated[int, Query(ge=1, le=50)] = 10
) -> Any:
    as_of = datetime.now(UTC).replace(second=0, microsecond=0)
    return cached(request, lambda: q.entity_spikes(db, as_of, limit=limit))


@router.get(
    "/analytics/cooccurrence",
    response_model=list[CoOccurrence],
    tags=["analytics"],
    summary="Entity pairs most often mentioned together",
)
def analytics_cooccurrence(
    request: Request, db: DB, rng: DateRangeDep, limit: Annotated[int, Query(ge=1, le=100)] = 30
) -> Any:
    return cached(request, lambda: q.co_occurrence(db, rng, limit=limit))


# ------------------------------------------------------------------------------------------
# Topics
# ------------------------------------------------------------------------------------------
@router.get(
    "/topics",
    response_model=list[TopicStat],
    tags=["topics"],
    summary="Topic ranking with share, change vs previous period and tone",
)
def list_topics(request: Request, db: DB, rng: DateRangeDep) -> Any:
    return cached(request, lambda: q.topics(db, rng))


@router.get(
    "/topics/taxonomy",
    response_model=list[TaxonomyTopic],
    tags=["topics"],
    summary="The controlled topic vocabulary",
)
def taxonomy(db: DB) -> Any:
    return [
        dict(r._mapping)
        for r in db.execute(
            text("SELECT slug, name_en, name_sq, description FROM core.topics ORDER BY sort_order")
        )
    ]


@router.get("/topics/{slug}", response_model=TopicDetail, responses=NOT_FOUND, tags=["topics"])
def topic_detail(
    request: Request,
    db: DB,
    rng: DateRangeDep,
    slug: Annotated[str, Path(pattern=r"^[a-z_]{2,48}$")],
) -> Any:
    result = cached(request, lambda: q.topic_detail(db, slug, rng))
    if result is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "unknown topic"})
    return result


# ------------------------------------------------------------------------------------------
# Entities
# ------------------------------------------------------------------------------------------
@router.get(
    "/entities",
    response_model=list[EntityStat],
    tags=["entities"],
    summary="Most-mentioned entities (searchable, filterable by type)",
)
def list_entities(
    request: Request,
    db: DB,
    rng: DateRangeDep,
    type: Annotated[Literal["person", "organization", "location"] | None, Query()] = None,
    search: Annotated[str | None, Query(min_length=2, max_length=80, alias="q")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> Any:
    return cached(
        request,
        lambda: q.top_entities(db, rng, entity_type=type, limit=limit, q=search, offset=offset),
    )


@router.get(
    "/entities/{entity_id}",
    response_model=EntityDetail,
    responses=NOT_FOUND,
    tags=["entities"],
    summary="Mentions over time, co-mentions, topics and sources",
)
def entity_detail(
    request: Request, db: DB, rng: DateRangeDep, entity_id: Annotated[int, Path(ge=1)]
) -> Any:
    result = cached(request, lambda: q.entity_detail(db, entity_id, rng))
    if result is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "unknown entity"})
    return result


# ------------------------------------------------------------------------------------------
# Sources
# ------------------------------------------------------------------------------------------
@router.get(
    "/sources",
    response_model=list[SourceStat],
    tags=["sources"],
    summary="Per-source volume, originality, tone and topic mix",
)
def list_sources(request: Request, db: DB, rng: DateRangeDep) -> Any:
    return cached(request, lambda: q.sources_compare(db, rng))


# ------------------------------------------------------------------------------------------
# Articles
# ------------------------------------------------------------------------------------------
@router.get(
    "/articles",
    response_model=Page[ArticleSummary],
    tags=["articles"],
    summary="Search and filter articles (metadata + AI analysis, links to originals)",
)
def list_articles(
    request: Request,
    db: DB,
    rng: DateRangeDep,
    search: Annotated[str | None, Query(alias="q", min_length=2, max_length=120)] = None,
    topic: Annotated[str | None, Query(pattern=r"^[a-z_]{2,48}$")] = None,
    entity: Annotated[int | None, Query(ge=1)] = None,
    sentiment: Literal["negative", "neutral", "positive"] | None = None,
    sort: Literal["newest", "oldest"] = "newest",
    page: Annotated[int, Query(ge=1, le=500)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Any:
    def compute() -> dict[str, Any]:
        total, items = q.search_articles(
            db,
            rng,
            q=search,
            topic=topic,
            entity_id=entity,
            sentiment=sentiment,
            sort=sort,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, math.ceil(total / page_size)),
        }

    return cached(request, compute)


@router.get(
    "/articles/{article_id}", response_model=ArticleDetail, responses=NOT_FOUND, tags=["articles"]
)
def article_detail(db: DB, article_id: Annotated[int, Path(ge=1)]) -> Any:
    result = q.article_detail(db, article_id)
    if result is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "unknown article"})
    return result
