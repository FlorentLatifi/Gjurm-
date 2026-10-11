import type { Params } from "@/shared/api/client";
import type {
  CoOccurrence,
  EntityDetail,
  EntitySpikes,
  EntityStat,
  Overview,
  SentimentSeries,
  SentimentShift,
  TopicDetail,
  TopicMomentum,
  TopicStat,
  VolumeSeries,
} from "@/shared/api/types";
import { apiQuery } from "@/shared/query/apiQuery";

export const overviewQuery = (p: Params) => apiQuery<Overview>("/api/v1/analytics/overview", p, "analytics");
export const volumeQuery = (p: Params) => apiQuery<VolumeSeries>("/api/v1/analytics/volume", p, "analytics");
export const sentimentQuery = (p: Params) => apiQuery<SentimentSeries>("/api/v1/analytics/sentiment", p, "analytics");
export const sentimentShiftQuery = () =>
  apiQuery<SentimentShift>("/api/v1/analytics/sentiment/shift", undefined, "analytics");
export const topicMomentumQuery = () =>
  apiQuery<TopicMomentum>("/api/v1/analytics/trends/topics", undefined, "analytics");
export const entitySpikesQuery = (limit = 10) =>
  apiQuery<EntitySpikes>("/api/v1/analytics/trends/entities", { limit }, "analytics");
export const coOccurrenceQuery = (p: Params) =>
  apiQuery<CoOccurrence[]>("/api/v1/analytics/cooccurrence", { ...p, limit: 20 }, "analytics");
export const topicsQuery = (p: Params) => apiQuery<TopicStat[]>("/api/v1/topics", p, "analytics");
export const topicQuery = (slug: string, p: Params) =>
  apiQuery<TopicDetail>(`/api/v1/topics/${encodeURIComponent(slug)}`, p, "analytics");
export const entitiesQuery = (p: Params) => apiQuery<EntityStat[]>("/api/v1/entities", p, "analytics");
export const entityQuery = (id: number, p: Params) =>
  apiQuery<EntityDetail>(`/api/v1/entities/${id}`, p, "analytics");
