import type { Params } from "@/shared/api/client";
import type { SourceProfile, SourceStat } from "@/shared/api/types";
import { apiQuery, useApiQuery } from "@/shared/query/apiQuery";

export const validSlug = (slug: string) => /^[a-z0-9-]{2,64}$/.test(slug);

export const sourcesQuery = (p: Params) => apiQuery<SourceStat[]>("/api/v1/sources", p, "analytics");
export const sourceProfileQuery = (slug: string, p: Params) =>
  apiQuery<SourceProfile>(`/api/v1/sources/${encodeURIComponent(slug)}`, p, "analytics");

export const useSources = (p: Params) => useApiQuery(sourcesQuery(p));
