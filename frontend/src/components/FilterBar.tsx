import { useId } from "react";

import { useSources } from "../api/hooks";
import { RANGE_PRESETS, useFilters } from "../lib/filters";

/** One filter row above the content it scopes: date range first, then outlet. */
export function FilterBar({
  showSources = true,
  presets = RANGE_PRESETS,
  defaultDays = 30,
  children,
}: {
  showSources?: boolean;
  presets?: readonly { days: number; label: string }[];
  defaultDays?: number;
  children?: React.ReactNode;
}) {
  const { filters, update } = useFilters(defaultDays);
  const { data: sources } = useSources({ days: 90 });
  const sourceId = useId();
  const options = (sources ?? []).filter((s) => s.articles > 0 || s.is_active);

  return (
    <div className="filters" role="group" aria-label="Filters">
      <div className="segmented" role="group" aria-label="Time range">
        {presets.map((p) => (
          <button
            key={p.days}
            type="button"
            aria-pressed={filters.days === p.days}
            onClick={() => update({ days: p.days })}
          >
            {p.label}
          </button>
        ))}
      </div>
      {showSources && (
        <div className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <label htmlFor={sourceId}>Outlet</label>
          <select
            id={sourceId}
            value={filters.sources[0] ?? ""}
            onChange={(e) => update({ sources: e.target.value ? [e.target.value] : [] })}
          >
            <option value="">All outlets</option>
            {options.map((s) => (
              <option key={s.slug} value={s.slug}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
      )}
      {children}
    </div>
  );
}
