import { articlesQuery } from "@/features/articles";
import type { EntityType } from "@/shared/api/types";
import { apiParamsOf, readFilters } from "@/shared/hooks/useFilters";

import {
  coOccurrenceQuery,
  entitiesQuery,
  entityQuery,
  entitySpikesQuery,
  overviewQuery,
  sentimentQuery,
  sentimentShiftQuery,
  topicMomentumQuery,
  topicQuery,
  topicsQuery,
  volumeQuery,
} from "./api";

const api = (search: URLSearchParams) => apiParamsOf(readFilters(search));

export function overviewQueries(search: URLSearchParams) {
  const p = api(search);
  return {
    overview: overviewQuery(p),
    volume: volumeQuery(p),
    sentiment: sentimentQuery(p),
    topics: topicsQuery(p),
    momentum: topicMomentumQuery(),
    spikes: entitySpikesQuery(6),
    latest: articlesQuery({ ...p, page_size: 8 }),
  };
}

export function trendsQueries(search: URLSearchParams) {
  const p = api(search);
  return {
    momentum: topicMomentumQuery(),
    spikes: entitySpikesQuery(15),
    shift: sentimentShiftQuery(),
    volume: volumeQuery(p),
    sentiment: sentimentQuery(p),
  };
}

export function topicsQueries(search: URLSearchParams) {
  return { topics: topicsQuery(api(search)) };
}

export function topicQueries(slug: string, search: URLSearchParams) {
  const p = api(search);
  return { topic: topicQuery(slug, p), articles: articlesQuery({ ...p, topic: slug, page_size: 10 }) };
}

export function entitiesState(search: URLSearchParams) {
  return { type: (search.get("type") ?? "") as EntityType | "", q: search.get("q") ?? "" };
}

export function entitiesQueries(search: URLSearchParams) {
  const p = api(search);
  const { type, q } = entitiesState(search);
  return {
    entities: entitiesQuery({ ...p, type: type || undefined, q: q.length >= 2 ? q : undefined, limit: 30 }),
    pairs: coOccurrenceQuery(p),
  };
}

export function entityQueries(id: number, search: URLSearchParams) {
  const p = api(search);
  return { entity: entityQuery(id, p), articles: articlesQuery({ ...p, entity: id, page_size: 10 }) };
}
