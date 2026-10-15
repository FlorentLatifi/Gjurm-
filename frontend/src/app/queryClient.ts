import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/shared/api/client";

/**
 * Freshness is set per query (shared/query/apiQuery.ts). Retries skip client errors: a 404 or a
 * 422 will not change by asking again.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (count, error) =>
        count < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
  },
});
