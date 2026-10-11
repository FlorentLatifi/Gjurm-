import type { Params } from "@/shared/api/client";
import type {
  CoOccurrence,
  EntityDetail,
  EntitySpikes,
  EntityStat,
  Overview,
  SentimentGroups,
  SentimentSeries,
  SentimentShift,
  TopicDetail,
  TopicMomentum,
  TopicStat,
  VolumeSeries,
} from "@/shared/api/types";
import { useApi } from "@/shared/query/useApi";

export const useOverview = (p: Params) => useApi<Overview>("/api/v1/analytics/overview", p);
export const useVolume = (p: Params) => useApi<VolumeSeries>("/api/v1/analytics/volume", p);
export const useSentiment = (p: Params) => useApi<SentimentSeries>("/api/v1/analytics/sentiment", p);
export const useSentimentBy = (p: Params, groupBy: "source" | "topic") =>
  useApi<SentimentGroups>("/api/v1/analytics/sentiment", { ...p, group_by: groupBy });
export const useSentimentShift = () => useApi<SentimentShift>("/api/v1/analytics/sentiment/shift");
export const useTopicMomentum = () => useApi<TopicMomentum>("/api/v1/analytics/trends/topics");
export const useEntitySpikes = (limit = 10) =>
  useApi<EntitySpikes>("/api/v1/analytics/trends/entities", { limit });
export const useCoOccurrence = (p: Params) =>
  useApi<CoOccurrence[]>("/api/v1/analytics/cooccurrence", { ...p, limit: 20 });
export const useTopics = (p: Params) => useApi<TopicStat[]>("/api/v1/topics", p);
export const useTopic = (slug: string, p: Params) =>
  useApi<TopicDetail>(`/api/v1/topics/${encodeURIComponent(slug)}`, p);
export const useEntities = (p: Params) => useApi<EntityStat[]>("/api/v1/entities", p);
export const useEntity = (id: number, p: Params) =>
  useApi<EntityDetail>(`/api/v1/entities/${id}`, p, Number.isInteger(id) && id > 0);
