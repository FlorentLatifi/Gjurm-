import { formatPercent } from "@/shared/lib/format";
import type { Segment } from "@/shared/model/ratings";
import "./coverage.css";
import { t, tn } from "@/shared/i18n";

/**
 * Ground News-style coverage bar: the distinct outlets that covered a story, split by one
 * dimension. Plain HTML (no chart library): a 2px surface gap between segments, a hatched fill
 * for unrated outlets, and the numbers always printed next to the bar so colour is never the
 * only carrier of meaning. Each segment has a hover title. `labels="inside"` prints each
 * segment's name and share on the segment itself, as Ground News' lead story does.
 */
export function CoverageBar({
  parts,
  size = "md",
  caption,
  labels = "nonzero",
  unit = (n) => tn(n, "{n} outlet", "{n} outlets"),
}: {
  parts: Segment[];
  size?: "xs" | "sm" | "md" | "lg";
  /** Accessible name prefix, e.g. "Coverage by perspective". */
  caption: string;
  /**
   * "all": every category, so a 0% side is visible (hatched unrated/other only when > 0).
   * "inside": on the segments (wide enough ones; the bar's name still carries every share).
   */
  labels?: "nonzero" | "all" | "none" | "inside";
  /** A segment's count in words, e.g. "3 outlets". */
  unit?: (n: number) => string;
}) {
  const total = parts.reduce((sum, p) => sum + p.value, 0);
  if (!total) return <span className="rank-meta">{t("No coverage data")}</span>;
  const shown = parts.filter((p) => p.value > 0);
  const text = shown
    .map((p) => `${p.label}: ${unit(p.value)} (${formatPercent(p.value / total)})`)
    .join(", ");
  return (
    <div className={`coverage coverage--${size}`}>
      <div className="coverage__bar" role="img" aria-label={`${caption}. ${text}.`}>
        {shown.map((p) => (
          <span
            key={p.key}
            className={`coverage__seg ${p.hatched ? "seg--hatched" : ""}`}
            style={{ flexGrow: p.value, background: p.color, color: p.ink }}
            title={`${p.label}: ${p.value} (${formatPercent(p.value / total)})`}
          >
            {labels === "inside" && p.value / total >= 0.08 && (
              <span className="coverage__inside" aria-hidden="true">
                {/* the name where it fits (never "unrated", the longest), the share always */}
                {p.value / total >= 0.3 && !p.hatched && `${p.label} `}
                {formatPercent(p.value / total)}
              </span>
            )}
          </span>
        ))}
      </div>
      {labels !== "none" && labels !== "inside" && (
        <div className="coverage__labels" aria-hidden="true">
          {(labels === "all" ? parts.filter((p) => p.value > 0 || !p.hatched) : shown).map((p) => (
            <span key={p.key} className="coverage__label">
              <span className={`dot ${p.hatched ? "seg--hatched" : ""}`} style={{ background: p.color }} />
              {p.label} <strong>{formatPercent(p.value / total)}</strong>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
