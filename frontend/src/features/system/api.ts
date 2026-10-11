import type { PublicStatus, TaxonomyTopic } from "@/shared/api/types";
import { apiQuery, useApiQuery } from "@/shared/query/apiQuery";

export const statusQuery = () => apiQuery<PublicStatus>("/api/v1/status", undefined, "status");
export const taxonomyQuery = () => apiQuery<TaxonomyTopic[]>("/api/v1/topics/taxonomy", undefined, "static");

export const useStatus = () => useApiQuery(statusQuery());
export const useTaxonomy = () => useApiQuery(taxonomyQuery());
