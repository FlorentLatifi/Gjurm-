import { entitySpikesQuery } from "@/features/analytics";
import { taxonomyQuery } from "@/features/system";
import { apiParamsOf, readFilters } from "@/shared/hooks/useFilters";

import { blindspotsQuery, storiesQuery, storyQuery } from "./api";

/**
 * What each stories page asks the API for, derived from its URL alone. The page and its route
 * loader both call these, so the loader's prefetch fills exactly the cache entries the page reads.
 */
export const FEED_DEFAULT_DAYS = 3;
export const BLINDSPOT_DEFAULT_DAYS = 7;

export function feedState(search: URLSearchParams) {
  return {
    sort: search.get("sort") === "latest" ? "latest" : "top",
    topic: search.get("topic") ?? "",
    country: search.get("country") ?? "",
    q: search.get("q") ?? "",
    page: Math.max(1, Number(search.get("page")) || 1),
  } as const;
}

export function feedQueries(search: URLSearchParams) {
  const filters = readFilters(search, FEED_DEFAULT_DAYS);
  const { sort, topic, country, q, page } = feedState(search);
  return {
    stories: storiesQuery({
      ...apiParamsOf(filters), sort, topic: topic || undefined, country: country || undefined, q: q || undefined,
      // single-outlet items are the long tail; the feed starts at stories two outlets covered
      min_sources: q ? 1 : 2, page, page_size: 15,
    }),
    // the left column's "Latest": the newest stories two outlets covered, whatever the order
    latest: storiesQuery({
      ...apiParamsOf(filters), sort: "latest", country: country || undefined, min_sources: 2, page: 1, page_size: 8,
    }),
    blindspots: blindspotsQuery({ days: Math.max(filters.days, 7) }),
    spikes: entitySpikesQuery(6),
    taxonomy: taxonomyQuery(),
  };
}

export function blindspotKind(search: URLSearchParams): "" | "perspective" | "region" {
  const k = search.get("kind");
  return k === "perspective" || k === "region" ? k : "";
}

export function blindspotQueries(search: URLSearchParams) {
  const kind = blindspotKind(search);
  return {
    blindspots: blindspotsQuery({
      ...apiParamsOf(readFilters(search, BLINDSPOT_DEFAULT_DAYS)), kind: kind || undefined, limit: 60,
    }),
  };
}

export function storyQueries(id: number) {
  return { story: storyQuery(id) };
}
