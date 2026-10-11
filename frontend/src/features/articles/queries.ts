import { taxonomyQuery } from "@/features/system";
import { apiParamsOf, readFilters } from "@/shared/hooks/useFilters";

import { articleQuery, articlesQuery } from "./api";

export function articlesState(search: URLSearchParams) {
  return {
    q: search.get("q") ?? "",
    topic: search.get("topic") ?? "",
    sentiment: search.get("sentiment") ?? "",
    sort: search.get("sort") === "oldest" ? "oldest" : "newest",
    entity: search.get("entity") ?? "",
    page: Math.max(1, Number(search.get("page")) || 1),
  } as const;
}

export function articlesQueries(search: URLSearchParams) {
  const { q, topic, sentiment, sort, entity, page } = articlesState(search);
  return {
    articles: articlesQuery({
      ...apiParamsOf(readFilters(search)), q: q || undefined, topic: topic || undefined,
      sentiment: sentiment || undefined, entity: entity || undefined, sort, page, page_size: 20,
    }),
    taxonomy: taxonomyQuery(),
  };
}

export function articleQueries(id: number) {
  return { article: articleQuery(id) };
}
