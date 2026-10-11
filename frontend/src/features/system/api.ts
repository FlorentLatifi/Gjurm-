import type { PublicStatus, TaxonomyTopic } from "@/shared/api/types";
import { useApi } from "@/shared/query/useApi";

export const useStatus = () => useApi<PublicStatus>("/api/v1/status");
export const useTaxonomy = () => useApi<TaxonomyTopic[]>("/api/v1/topics/taxonomy");
