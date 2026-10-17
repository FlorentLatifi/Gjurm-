"""Typed API response models — the public contract, rendered into the OpenAPI document."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field

from gjurme import taxonomy

T = TypeVar("T")


class Model(BaseModel):
    # Response fields with a default are still always present in the JSON; say so in the OpenAPI
    # schema (the frontend's API types are generated from it, docs/architecture/frontend_system.md).
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )


SentimentLabel = Literal["negative", "neutral", "positive"]
EntityType = Literal["person", "organization", "location"]


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
    method_sq: str = Field(description="The same description in Albanian")


class TopicName(Model):
    """A topic reference; its Albanian name comes from the taxonomy."""

    slug: str
    name_en: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def name_sq(self) -> str:
        return taxonomy.name_sq(self.slug) or self.name_en


# ------------------------------------------------------------------------------------------
# Overview
# ------------------------------------------------------------------------------------------
class SentimentBreakdown(Model):
    negative: int
    neutral: int
    positive: int
    average: float | None


class TopTopic(TopicName):
    articles: int
    share: float | None


class EntityRef(Model):
    id: int
    name: str
    type: EntityType


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


class SentimentShiftItem(TopicName):
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


class TopicMomentumItem(TopicName):
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def description_sq(self) -> str:
        return taxonomy.DESCRIPTION_SQ.get(self.slug, self.description)


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


class TopicSlice(TopicName):
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
    a_type: EntityType
    b_id: int
    b_name: str
    b_type: EntityType
    together: int


# ------------------------------------------------------------------------------------------
# Sources
# ------------------------------------------------------------------------------------------
class TopicCount(Model):
    slug: str
    articles: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def name_en(self) -> str:
        topic = taxonomy.TOPIC_BY_SLUG.get(self.slug)
        return topic.name_en if topic else self.slug

    @computed_field  # type: ignore[prop-decorator]
    @property
    def name_sq(self) -> str:
        return taxonomy.name_sq(self.slug) or self.slug


BiasRating = Literal["left", "lean_left", "center", "lean_right", "right", "unrated"]
FactualityRating = Literal["very_high", "high", "mixed", "low", "very_low", "unrated"]
OwnershipType = Literal[
    "private", "media_group", "public", "state", "public_international", "nonprofit", "unknown"
]


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
    bias: BiasRating = Field(description="Editorial perspective rating (sources.yaml)")
    factuality: FactualityRating
    ownership: OwnershipType
    owner: str | None
    stories: int = Field(description="Stories (started in the range) this outlet covered")
    first_reports: int = Field(
        description="Stories covered by 2+ outlets that this outlet published first"
    )
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
# Stories
# ------------------------------------------------------------------------------------------
class BiasCoverage(Model):
    left: int
    center: int
    right: int
    unrated: int


class FactualityCoverage(Model):
    high: int
    mixed: int
    low: int
    unrated: int


class Coverage(Model):
    """Distinct outlets that covered a story, split four ways."""

    bias: BiasCoverage = Field(description="By perspective group (left/lean left = left, …)")
    factuality: FactualityCoverage
    ownership: dict[str, int] = Field(description="By ownership type")
    region: dict[str, int] = Field(description="By the outlet's country (XK, AL, MK, REG …)")


class ToneMix(Model):
    negative: int
    neutral: int
    positive: int


class StorySource(Model):
    slug: str
    name: str
    bias: BiasRating
    country: str


class Blindspot(Model):
    kind: Literal["perspective", "region"]
    missing: str = Field(
        description="perspective: the side that barely covered it (left/right); "
        "region: the country whose outlets did not cover it"
    )


class StorySummary(Model):
    id: int
    title: str = Field(description="Headline of the most typical article (closest to centroid)")
    url: str = Field(description="Link to that article at its publisher")
    language: str
    summary_en: str | None
    summary_sq: str | None = Field(None, description="The summary in Albanian (prompt v1.2+)")
    source_slug: str
    source_name: str
    first_published_at: datetime
    last_published_at: datetime
    article_count: int
    source_count: int
    topic_slug: str | None
    topic_name: str | None
    first_source_slug: str = Field(description="Outlet that published first")
    first_source_name: str
    coverage: Coverage
    tone: ToneMix
    sources: list[StorySource]
    blindspots: list[Blindspot]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def topic_name_sq(self) -> str | None:
        return taxonomy.name_sq(self.topic_slug, self.topic_name)


class StoryArticle(Model):
    id: int
    title: str
    url: str
    published_at: datetime
    language: str
    summary_en: str | None
    summary_sq: str | None = Field(None, description="The summary in Albanian (prompt v1.2+)")
    sentiment_label: SentimentLabel | None
    source_slug: str
    source_name: str
    source_country: str
    source_bias: BiasRating
    source_factuality: FactualityRating
    source_ownership: OwnershipType
    is_first: bool


class EntityArticles(EntityRef):
    articles: int


class TopicArticles(TopicName):
    articles: int


class StoryDetail(StorySummary):
    articles: list[StoryArticle]
    entities: list[EntityArticles]
    topics: list[TopicArticles]
    related: list[StorySummary] = Field(description="Stories within 3 days sharing 2+ names")


class Blindspots(WithMethod):
    items: list[StorySummary]


class SharedCoverage(Model):
    slug: str
    name: str
    bias: BiasRating
    shared: int


class SourceProfile(Model):
    slug: str
    name: str
    homepage_url: str
    language: str
    country: str
    is_active: bool
    verification_status: str
    last_success_at: datetime | None
    bias: BiasRating
    factuality: FactualityRating
    ownership: OwnershipType
    owner: str | None
    ratings_note: str | None = Field(description="What the bias/factuality ratings are based on")
    range: DateRange
    articles: int
    avg_sentiment: float | None
    stories: int
    first_reports: int
    exclusives: int = Field(description="Stories only this outlet covered")
    coverage_share: float | None = Field(
        description="Share of the multi-outlet stories of the period this outlet covered"
    )
    top_topics: list[TopicSlice]
    top_entities: list[EntityMentions]
    overlap: list[SharedCoverage] = Field(description="Outlets that covered the same stories")
    recent_stories: list[StorySummary]


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
    summary_sq: str | None = Field(None, description="The summary in Albanian (prompt v1.2+)")
    sentiment_label: SentimentLabel | None
    sentiment_score: float | None
    event_type: str | None
    enrichment_status: str
    duplicate_of_id: int | None
    story_id: int | None = None
    source_slug: str
    source_name: str
    topic_slug: str | None
    topic_name: str | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def topic_name_sq(self) -> str | None:
        return taxonomy.name_sq(self.topic_slug, self.topic_name)


class ArticleTopicRef(TopicName):
    is_primary: bool


class RelatedArticle(Model):
    id: int
    title: str
    url: str
    published_at: datetime
    source_slug: str
    source_name: str


class ArticleDetail(Model):
    id: int
    title: str
    url: str
    published_at: datetime
    published_at_estimated: bool
    language: str
    summary_en: str | None
    summary_sq: str | None = Field(None, description="The summary in Albanian (prompt v1.2+)")
    sentiment_label: SentimentLabel | None
    sentiment_score: float | None
    event_type: str | None
    countries: list[str]
    enrichment_status: str
    enrichment_confidence: float | None
    feed_categories: list[str]
    author: str | None
    duplicate_of_id: int | None
    story_id: int | None = None
    enriched_at: datetime | None
    analysis_method: Literal["ai", "rules"] | None = Field(
        None, description="How topics, tone and entities were assigned: an LLM or keyword rules"
    )
    analysis_model: str | None = Field(None, description="LLM model id when analysis_method=ai")
    source_slug: str
    source_name: str
    source_url: str
    topic_slug: str | None
    topic_name: str | None
    topics: list[ArticleTopicRef]
    entities: list[EntityRef]
    related: list[RelatedArticle]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def topic_name_sq(self) -> str | None:
        return taxonomy.name_sq(self.topic_slug, self.topic_name)


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


class AnalysisMode(Model):
    mode: Literal["ai", "rules", "mixed", "none"] = Field(
        description="How articles of the last 30 days were analysed (LLM, keyword rules, or both)"
    )
    rule_based_share: float | None = Field(
        description="Share of analysed articles (last 30 days) that used keyword rules"
    )
    model: str | None = Field(description="Most used LLM model, if any")


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
    analysis: AnalysisMode
    demo_data: bool
    version: str


class TaxonomyTopic(Model):
    slug: str
    name_en: str
    name_sq: str
    description: str
