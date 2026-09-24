import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/** Global filter state lives in the URL, so every view is a shareable, bookmarkable link. */
export const RANGE_PRESETS = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
] as const;

export interface Filters {
  days: number;
  sources: string[];
}

export function useFilters() {
  const [params, setParams] = useSearchParams();
  const filters: Filters = useMemo(() => {
    const raw = Number(params.get("days"));
    const days = Number.isInteger(raw) && raw >= 1 && raw <= 366 ? raw : 30;
    return { days, sources: params.getAll("source").filter((s) => /^[a-z0-9-]{2,64}$/.test(s)) };
  }, [params]);

  const update = useCallback(
    (next: Partial<Filters>) => {
      setParams(
        (prev) => {
          const out = new URLSearchParams(prev);
          if (next.days !== undefined) {
            if (next.days === 30) out.delete("days");
            else out.set("days", String(next.days));
          }
          if (next.sources !== undefined) {
            out.delete("source");
            next.sources.forEach((s) => out.append("source", s));
          }
          out.delete("page");
          return out;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const apiParams = useMemo(
    () => ({ days: filters.days, source: filters.sources.length ? filters.sources : undefined }),
    [filters],
  );

  return { filters, update, apiParams };
}

/** Carry the current global filters onto an internal link. */
export function withFilters(path: string, filters: Filters, extra: Record<string, string> = {}): string {
  const out = new URLSearchParams(extra);
  if (filters.days !== 30) out.set("days", String(filters.days));
  filters.sources.forEach((s) => out.append("source", s));
  const qs = out.toString();
  return qs ? `${path}?${qs}` : path;
}
