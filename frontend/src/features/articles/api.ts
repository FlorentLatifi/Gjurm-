import type { Params } from "@/shared/api/client";
import type { ArticleDetail, ArticleSummary, Page } from "@/shared/api/types";
import { apiQuery } from "@/shared/query/apiQuery";

export const articlesQuery = (p: Params) => apiQuery<Page<ArticleSummary>>("/api/v1/articles", p, "feed");
export const articleQuery = (id: number) => apiQuery<ArticleDetail>(`/api/v1/articles/${id}`, undefined, "feed");
