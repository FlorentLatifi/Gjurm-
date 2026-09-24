"""Typed API response models — the public contract, rendered into the OpenAPI document."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(Model):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(Model):
    error: ErrorBody


class DateRange(Model):
    start: date
    end: date
    days: int


class Page(Model, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class WithMethod(Model):
    method: str = Field(description="Plain-language description of how the numbers are computed")


# ------------------------------------------------------------------------------------------
# Overview
# ------------------------------------------------------------------------------------------
class SentimentBreakdown(Model):
    negative: int
    neutral: int
    positive: int
    average: float | None


class TopTopic(Model):
    slug: str
    name_en: str
    articles: int
    share: float | None


class EntityRef(Model):
    id: int
    name: str
    type: Literal["person", "organization", "location"]


class EntityStat(EntityRef):
    mentions: int
    previous: int
    change: float | None
    avg_sentiment: float | None
    sources: int


class Overview(Model):
    range: DateRange
    articles_total: int
    articles: int
    unique_stories: int
    today: int
    yesterday: int
    sources: int
    enriched: int
    enriched_share: float | None
    sentiment: SentimentBreakdown
    top_topic: TopTopic | None
    top_entity: EntityStat | None
    last_ingested_at: datetime | None


# ------------------------------------------------------------------------------------------
# Time series
# ------------------------------------------------------------------------------------------
class VolumePoint(Model):
    day: date
    articles: int
    stories: int
    ma7: float | None


class GroupedPoint(Model):
    day: date
    key: str
    articles: int


class VolumeSeries(WithMethod):
    series: list[VolumePoint]


class GroupedVolumeSeries(WithMethod):
    group_by: str
    series: list[GroupedPoint]


class SentimentPoint(Model):
    day: date
    negative: int
    neutral: int
    positive: int
    average: float | None
    ma7: float | None


class SentimentSeries(WithMethod):
    series: list[SentimentPoint]


class SentimentGroup(Model):
    key: str
    n: int
    average: float | None
    negative: int
    neutral: int
    positive: int


class SentimentGroups(Model):
    group_by: str
    groups: list[SentimentGroup]


class SentimentShiftItem(Model):
    slug: str
    name_en: str
    current: float | None
    previous: float | None
    n_current: int
    n_previous: int
    delta: float | None


class SentimentShift(WithMethod):
    window_days: int
    items: list[SentimentShiftItem]


# ------------------------------------------------------------------------------------------
# Topics
# ------------------------------------------------------------------------------------------
class TopicStat(Model):
    slug: str
    name_en: str
    name_sq: str
    articles: int
    previous: int
    share: float | None
    change: float | None
    avg_sentiment: float | None
    negative: int
    positive: int


class TopicMomentumItem(Model):
    slug: str
    name_en: str
    current: int
    previous: int
    growth: float | None


class TopicMomentum(WithMethod):
    window_days: int
    items: list[TopicMomentumItem]


class TopicInfo(Model):
    id: int
    slug: str
    name_en: str
    name_sq: str
    description: str


class TopicSeriesPoint(Model):
    day: date
    articles: int
    avg_sentiment: float | None


class EntityMentions(EntityRef):
    mentions: int


class SourceSlice(Model):
    slug: str
    name: str
    articles: int
    avg_sentiment: float | None = None


class TopicDetail(Model):
    topic: TopicInfo
    series: list[TopicSeriesPoint]
    top_entities: list[EntityMentions]
    sources: list[SourceSlice]


# ------------------------------------------------------------------------------------------
# Entities
# ------------------------------------------------------------------------------------------
class EntitySpike(EntityRef):
    last_24h: int
    baseline_mean: float | None
    baseline_std: float | None
    z: float | None
    is_spike: bool


class EntitySpikes(WithMethod):
    as_of: datetime
    items: list[EntitySpike]


class EntityInfo(EntityRef):
    first_seen_at: datetime


class EntitySeriesPoint(Model):
    day: date
    mentions: int
    avg_sentiment: float | None


class CoMention(EntityRef):
    together: int


class TopicSlice(Model):
    slug: str
    name_en: str
    articles: int


class EntityDetail(Model):
    entity: EntityInfo
    mentions: int
    avg_sentiment: float | None
    series: list[EntitySeriesPoint]
    co_mentions: list[CoMention]
    topics: list[TopicSlice]
    sources: list[SourceSlice]


class CoOccurrence(Model):
    a_id: int
    a_name: str
    a_type: str
    b_id: int
    b_name: str
    b_type: str
    together: int


# ------------------------------------------------------------------------------------------
# Sources
# ------------------------------------------------------------------------------------------
class TopicCount(Model):
    slug: str
    articles: int


class SourceStat(Model):
    slug: str
    name: str
    homepage_url: str
    language: str
    country: str
    is_active: bool
    verification_status: str
    last_success_at: datetime | None
    consecutive_failures: int
    articles: int
    original: int
    per_day: float | None
    avg_sentiment: float | None
    negative: int
    neutral: int
    positive: int
    last_article_at: datetime | None
    top_topics: list[TopicCount]


# ------------------------------------------------------------------------------------------
# Articles
# ------------------------------------------------------------------------------------------
class ArticleSummary(Model):
    id: int
    title: str
    url: str
    published_at: datetime
    published_at_estimated: bool
    language: str
    summary_en: str | None
    sentiment_label: str | None
    sentiment_score: float | None
    event_type: str | None
    enrichment_status: str
    duplicate_of_id: int | None
    source_slug: str
    source_name: str
    topic_slug: str | None
    topic_name: str | None


class ArticleTopicRef(Model):
    slug: str
    name_en: str
    is_primary: bool


class RelatedArticle(Model):
    id: int
    title: str
    url: str
    published_at: datetime
    source_name: str


class ArticleDetail(Model):
    id: int
    title: str
    url: str
    published_at: datetime
    published_at_estimated: bool
    language: str
    summary_en: str | None
    sentiment_label: str | None
    sentiment_score: float | None
    event_type: str | None
    countries: list[str]
    enrichment_status: str
    enrichment_confidence: float | None
    feed_categories: list[str]
    author: str | None
    duplicate_of_id: int | None
    enriched_at: datetime | None
    source_slug: str
    source_name: str
    source_url: str
    topic_slug: str | None
    topic_name: str | None
    topics: list[ArticleTopicRef]
    entities: list[EntityRef]
    related: list[RelatedArticle]


# ------------------------------------------------------------------------------------------
# Status / health
# ------------------------------------------------------------------------------------------
class Health(Model):
    status: Literal["ok", "degraded", "down"]
    version: str
    database: bool | None = None
    migrations: str | None = None


class SourceHealth(Model):
    slug: str
    name: str
    is_active: bool
    verification_status: str
    last_success_at: datetime | None
    consecutive_failures: int


class PublicStatus(Model):
    status: Literal["ok", "degraded", "stale"]
    last_run_at: datetime | None
    last_run_status: str | None
    last_success_at: datetime | None
    minutes_since_success: float | None
    scheduler_heartbeat_at: datetime | None
    articles_last_24h: int
    enrichment_backlog: int
    sources: list[SourceHealth]
    demo_data: bool
    version: str


class TaxonomyTopic(Model):
    slug: str
    name_en: str
    name_sq: str
    description: str
