import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiGet, type Params } from "@/shared/api/client";

/**
 * One query per endpoint. `keepPreviousData` makes refetches hold the previous render (charts dim
 * instead of flashing skeletons when filters change); the backend refreshes every 15 minutes, so a
 * 60-second stale time avoids pointless refetches.
 */
export function useApi<T>(path: string, params?: Params, enabled = true) {
  return useQuery({
    queryKey: [path, params],
    queryFn: ({ signal }) => apiGet<T>(path, params, signal),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    enabled,
  });
}
