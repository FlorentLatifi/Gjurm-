import type { Params } from "@/shared/api/client";
import type { Blindspots, Page, StoryDetail, StorySummary } from "@/shared/api/types";
import { useApi } from "@/shared/query/useApi";

export const useStories = (p: Params) => useApi<Page<StorySummary>>("/api/v1/stories", p);
export const useStory = (id: number) =>
  useApi<StoryDetail>(`/api/v1/stories/${id}`, undefined, Number.isInteger(id) && id > 0);
export const useBlindspots = (p: Params) => useApi<Blindspots>("/api/v1/stories/blindspots", p);
