import type { Params } from "@/shared/api/client";
import type { ArticleDetail, ArticleSummary, Page } from "@/shared/api/types";
import { useApi } from "@/shared/query/useApi";

export const useArticles = (p: Params) => useApi<Page<ArticleSummary>>("/api/v1/articles", p);
export const useArticle = (id: number) =>
  useApi<ArticleDetail>(`/api/v1/articles/${id}`, undefined, Number.isInteger(id) && id > 0);
