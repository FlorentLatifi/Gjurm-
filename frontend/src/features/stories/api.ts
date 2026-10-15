import type { Params } from "@/shared/api/client";
import type { Blindspots, Page, StoryDetail, StorySummary } from "@/shared/api/types";
import { apiQuery } from "@/shared/query/apiQuery";

export const storiesQuery = (p: Params) => apiQuery<Page<StorySummary>>("/api/v1/stories", p, "feed");
export const storyQuery = (id: number) => apiQuery<StoryDetail>(`/api/v1/stories/${id}`, undefined, "feed");
export const blindspotsQuery = (p: Params) => apiQuery<Blindspots>("/api/v1/stories/blindspots", p, "feed");
