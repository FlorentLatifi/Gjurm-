import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";

import { apiGet, type Params } from "@/shared/api/client";

/**
 * How long each kind of data stays fresh (docs/architecture/frontend_system.md §2). The
 * pipeline refreshes every 30 minutes and the API sends `max-age=60`.
 */
export const FRESHNESS = {
  /** stories, story pages, blindspots, articles: new items arrive all day */
  feed: { staleTime: 60_000, refetchOnWindowFocus: true },
  /** dashboards: change only when the pipeline runs */
  analytics: { staleTime: 5 * 60_000 },
  /** the topic taxonomy: changes only with a deploy */
  static: { staleTime: Infinity },
  /** the status pill must stay honest while the tab is open */
  status: { staleTime: 60_000, refetchInterval: 5 * 60_000 },
} as const;

export type Freshness = keyof typeof FRESHNESS;

/**
 * The single definition of an endpoint's query: the hook, route loaders and hover prefetch all
 * use it, so they share one cache entry. Keys are [path, params]; the app never writes, so
 * nothing needs to invalidate groups of keys.
 */
export function apiQuery<T>(path: string, params: Params | undefined, freshness: Freshness) {
  return queryOptions({
    queryKey: [path, params ?? null] as const,
    queryFn: ({ signal }) => apiGet<T>(path, params, signal),
    ...FRESHNESS[freshness],
  });
}

type ApiQueryOptions<T> = ReturnType<typeof apiQuery<T>>;

/**
 * Reads an apiQuery. While the same resource refetches with new filters, the previous result
 * stays on screen (dimmed by Card) instead of a skeleton; a different resource (another story,
 * another entity) never shows the previous one's data.
 */
export function useApiQuery<T>(options: ApiQueryOptions<T>, enabled = true) {
  return useQuery({
    ...options,
    enabled,
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[0] === options.queryKey[0] ? keepPreviousData(previous) : undefined,
  });
}
