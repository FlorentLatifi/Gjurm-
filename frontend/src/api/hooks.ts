import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiGet, type Params } from "./client";
import type {
  ArticleDetail,
  ArticleSummary,
  CoOccurrence,
  EntityDetail,
  EntitySpikes,
  EntityStat,
  Overview,
  Page,
  PublicStatus,
  SentimentGroups,
  SentimentSeries,
  SentimentShift,
  SourceStat,
  TaxonomyTopic,
  TopicDetail,
  TopicMomentum,
  TopicStat,
  VolumeSeries,
} from "./types";

/**
 * One hook per endpoint. `keepPreviousData` makes refetches hold the previous render (charts dim
 * instead of flashing skeletons when filters change); the backend refreshes every 15 minutes, so a
 * 60-second stale time avoids pointless refetches.
 */
function useApi<T>(path: string, params?: Params, enabled = true) {
  return useQuery({
    queryKey: [path, params],
    queryFn: ({ signal }) => apiGet<T>(path, params, signal),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    enabled,
  });
}

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
export const useTaxonomy = () => useApi<TaxonomyTopic[]>("/api/v1/topics/taxonomy");
export const useTopic = (slug: string, p: Params) =>
  useApi<TopicDetail>(`/api/v1/topics/${encodeURIComponent(slug)}`, p);
export const useEntities = (p: Params) => useApi<EntityStat[]>("/api/v1/entities", p);
export const useEntity = (id: number, p: Params) =>
  useApi<EntityDetail>(`/api/v1/entities/${id}`, p, Number.isInteger(id) && id > 0);
export const useSources = (p: Params) => useApi<SourceStat[]>("/api/v1/sources", p);
export const useArticles = (p: Params) => useApi<Page<ArticleSummary>>("/api/v1/articles", p);
export const useArticle = (id: number) =>
  useApi<ArticleDetail>(`/api/v1/articles/${id}`, undefined, Number.isInteger(id) && id > 0);
export const useStatus = () => useApi<PublicStatus>("/api/v1/status");
