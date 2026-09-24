/** Mirrors backend/src/gjurme/api/schemas.py — the public API contract. */

export type EntityType = "person" | "organization" | "location";
export type SentimentLabel = "negative" | "neutral" | "positive";

export interface DateRange {
  start: string;
  end: string;
  days: number;
}

export interface EntityRef {
  id: number;
  name: string;
  type: EntityType;
}

export interface EntityStat extends EntityRef {
  mentions: number;
  previous: number;
  change: number | null;
  avg_sentiment: number | null;
  sources: number;
}

export interface Overview {
  range: DateRange;
  articles_total: number;
  articles: number;
  unique_stories: number;
  today: number;
  yesterday: number;
  sources: number;
  enriched: number;
  enriched_share: number | null;
  sentiment: { negative: number; neutral: number; positive: number; average: number | null };
  top_topic: { slug: string; name_en: string; articles: number; share: number | null } | null;
  top_entity: EntityStat | null;
  last_ingested_at: string | null;
}

export interface VolumePoint {
  day: string;
  articles: number;
  stories: number;
  ma7: number | null;
}
export interface VolumeSeries {
  method: string;
  series: VolumePoint[];
}

export interface SentimentPoint {
  day: string;
  negative: number;
  neutral: number;
  positive: number;
  average: number | null;
  ma7: number | null;
}
export interface SentimentSeries {
  method: string;
  series: SentimentPoint[];
}
export interface SentimentGroup {
  key: string;
  n: number;
  average: number | null;
  negative: number;
  neutral: number;
  positive: number;
}
export interface SentimentGroups {
  group_by: string;
  groups: SentimentGroup[];
}
export interface SentimentShift {
  method: string;
  window_days: number;
  items: {
    slug: string;
    name_en: string;
    current: number | null;
    previous: number | null;
    n_current: number;
    n_previous: number;
    delta: number | null;
  }[];
}

export interface TopicStat {
  slug: string;
  name_en: string;
  name_sq: string;
  articles: number;
  previous: number;
  share: number | null;
  change: number | null;
  avg_sentiment: number | null;
  negative: number;
  positive: number;
}

export interface TopicMomentum {
  method: string;
  window_days: number;
  items: { slug: string; name_en: string; current: number; previous: number; growth: number | null }[];
}

export interface TopicDetail {
  topic: { id: number; slug: string; name_en: string; name_sq: string; description: string };
  series: { day: string; articles: number; avg_sentiment: number | null }[];
  top_entities: (EntityRef & { mentions: number })[];
  sources: { slug: string; name: string; articles: number; avg_sentiment: number | null }[];
}

export interface EntitySpike extends EntityRef {
  last_24h: number;
  baseline_mean: number | null;
  baseline_std: number | null;
  z: number | null;
  is_spike: boolean;
}
export interface EntitySpikes {
  method: string;
  as_of: string;
  items: EntitySpike[];
}

export interface EntityDetail {
  entity: EntityRef & { first_seen_at: string };
  mentions: number;
  avg_sentiment: number | null;
  series: { day: string; mentions: number; avg_sentiment: number | null }[];
  co_mentions: (EntityRef & { together: number })[];
  topics: { slug: string; name_en: string; articles: number }[];
  sources: { slug: string; name: string; articles: number; avg_sentiment: number | null }[];
}

export interface CoOccurrence {
  a_id: number;
  a_name: string;
  a_type: EntityType;
  b_id: number;
  b_name: string;
  b_type: EntityType;
  together: number;
}

export interface SourceStat {
  slug: string;
  name: string;
  homepage_url: string;
  language: string;
  country: string;
  is_active: boolean;
  verification_status: string;
  last_success_at: string | null;
  consecutive_failures: number;
  articles: number;
  original: number;
  per_day: number | null;
  avg_sentiment: number | null;
  negative: number;
  neutral: number;
  positive: number;
  last_article_at: string | null;
  top_topics: { slug: string; articles: number }[];
}

export interface ArticleSummary {
  id: number;
  title: string;
  url: string;
  published_at: string;
  published_at_estimated: boolean;
  language: string;
  summary_en: string | null;
  sentiment_label: SentimentLabel | null;
  sentiment_score: number | null;
  event_type: string | null;
  enrichment_status: string;
  duplicate_of_id: number | null;
  source_slug: string;
  source_name: string;
  topic_slug: string | null;
  topic_name: string | null;
}

export interface ArticleDetail extends ArticleSummary {
  countries: string[];
  enrichment_confidence: number | null;
  feed_categories: string[];
  author: string | null;
  enriched_at: string | null;
  source_url: string;
  topics: { slug: string; name_en: string; is_primary: boolean }[];
  entities: EntityRef[];
  related: { id: number; title: string; url: string; published_at: string; source_name: string }[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface PublicStatus {
  status: "ok" | "degraded" | "stale";
  last_run_at: string | null;
  last_run_status: string | null;
  last_success_at: string | null;
  minutes_since_success: number | null;
  scheduler_heartbeat_at: string | null;
  articles_last_24h: number;
  enrichment_backlog: number;
  sources: {
    slug: string;
    name: string;
    is_active: boolean;
    verification_status: string;
    last_success_at: string | null;
    consecutive_failures: number;
  }[];
  demo_data: boolean;
  version: string;
}

export interface TaxonomyTopic {
  slug: string;
  name_en: string;
  name_sq: string;
  description: string;
}
