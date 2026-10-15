import { apiParamsOf, readFilters } from "@/shared/hooks/useFilters";

import { sourceProfileQuery, sourcesQuery } from "./api";

export function sourcesQueries(search: URLSearchParams) {
  return { sources: sourcesQuery(apiParamsOf(readFilters(search))) };
}

export function sourceProfileQueries(slug: string, search: URLSearchParams) {
  return { profile: sourceProfileQuery(slug, { days: readFilters(search).days }) };
}
