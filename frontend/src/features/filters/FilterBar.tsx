import { useId } from "react";

import { useSources } from "@/features/sources";
import { RANGE_PRESETS, useFilters } from "@/shared/hooks/useFilters";
import { t, tn } from "@/shared/i18n";

/** One filter row above the content it scopes: date range first, then outlet. */
export function FilterBar({
  showSources = true,
  presets = RANGE_PRESETS,
  defaultDays = 30,
  children,
}: {
  showSources?: boolean;
  /** Ranges in days; 1 reads "Today". */
  presets?: readonly number[];
  defaultDays?: number;
  children?: React.ReactNode;
}) {
  const { filters, update } = useFilters(defaultDays);
  const { data: sources } = useSources({ days: 90 });
  const sourceId = useId();
  const options = (sources ?? []).filter((s) => s.articles > 0 || s.is_active);

  return (
    <div className="filters" role="group" aria-label={t("Filters")}>
      <div className="segmented" role="group" aria-label={t("Time range")}>
        {presets.map((days) => (
          <button
            key={days}
            type="button"
            aria-pressed={filters.days === days}
            onClick={() => update({ days })}
          >
            {days === 1 ? t("Today") : tn(days, "{n} day", "{n} days")}
          </button>
        ))}
      </div>
      {showSources && (
        <div className="field field--inline">
          <label htmlFor={sourceId}>{t("Outlet")}</label>
          <select
            id={sourceId}
            value={filters.sources[0] ?? ""}
            onChange={(e) => update({ sources: e.target.value ? [e.target.value] : [] })}
          >
            <option value="">{t("All outlets")}</option>
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
