import type { Params } from "@/shared/api/client";
import type { SourceProfile, SourceStat } from "@/shared/api/types";
import { useApi } from "@/shared/query/useApi";

export const useSources = (p: Params) => useApi<SourceStat[]>("/api/v1/sources", p);
export const useSourceProfile = (slug: string, p: Params) =>
  useApi<SourceProfile>(`/api/v1/sources/${encodeURIComponent(slug)}`, p, /^[a-z0-9-]{2,64}$/.test(slug));
