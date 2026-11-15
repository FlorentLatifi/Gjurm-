import { formatPercent } from "@/shared/lib/format";
import type { Segment } from "@/shared/model/ratings";
import "./coverage.css";
import { t, tn } from "@/shared/i18n";

/**
 * The coverage bar: the distinct outlets that covered a story, split by one dimension. A thin
 * ruled band, as a measure printed under a headline: plain HTML (no chart library), a 2px gap
 * between segments, a hatched fill for unrated outlets, an empty dashed slot where a side is
 * missing (a blindspot), and the numbers always printed next to it so colour is never the only
 * carrier of meaning. With three to ten outlets a count says more than a share, so the labels
 * print counts; `labels="shares"` prints each share large with its count, for a story's own page.
 */
export function CoverageBar({
  parts,
  size = "md",
  caption,
  labels = "nonzero",
  missing = [],
  unit = (n) => tn(n, "{n} outlet", "{n} outlets"),
}: {
  parts: Segment[];
  size?: "sm" | "md" | "lg";
  /** Accessible name prefix, e.g. "Coverage by perspective". */
  caption: string;
  /** "all": every category, so a side nobody covered is listed (hatched unrated/other only when > 0). */
  labels?: "nonzero" | "all" | "none" | "shares";
  /** Keys of segments nobody covered that should show as an empty slot: the story's blindspots. */
  missing?: string[];
  /** A segment's count in words, e.g. "3 outlets". */
  unit?: (n: number) => string;
}) {
  const total = parts.reduce((sum, p) => sum + p.value, 0);
  if (!total) return <span className="rank-meta">{t("No coverage data")}</span>;
  const shown = parts.filter((p) => p.value > 0);
  const text = shown
    .map((p) => `${p.label}: ${unit(p.value)} (${formatPercent(p.value / total)})`)
    .join(", ");
  const listed = labels === "nonzero" ? shown : parts.filter((p) => p.value > 0 || !p.hatched);
  return (
    <div className={`coverage coverage--${size}`}>
      <div className="coverage__bar" role="img" aria-label={`${caption}. ${text}.`}>
        {parts.map((p) =>
          p.value > 0 ? (
            <span
              key={p.key}
              className={`coverage__seg ${p.hatched ? "seg--hatched" : ""}`}
              style={{ flexGrow: p.value, background: p.color }}
              title={`${p.label}: ${p.value} (${formatPercent(p.value / total)})`}
            />
          ) : missing.includes(p.key) ? (
            <span key={p.key} className="coverage__seg coverage__seg--missing" title={`${p.label}: 0`} />
          ) : null,
        )}
      </div>
      {labels !== "none" && (
        <div className={`coverage__labels ${labels === "shares" ? "coverage__labels--shares" : ""}`} aria-hidden="true">
          {listed.map((p) => (
            <span key={p.key} className="coverage__label">
              {labels === "shares" && <strong className="coverage__share">{formatPercent(p.value / total)}</strong>}
              <span>
                {(p.keyed || p.hatched) && (
                  <span className={`swatch ${p.hatched ? "seg--hatched" : ""}`} style={{ background: p.color }} />
                )}
                {p.label}
                {labels === "shares" ? " · " : " "}
                <strong>{p.value}</strong>
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
