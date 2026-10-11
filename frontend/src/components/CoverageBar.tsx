import type { Coverage } from "../api/types";
import { formatPercent } from "../lib/format";
import { type Lens, LENS_LABEL, type Segment, segments } from "../lib/ratings";

/**
 * Ground News-style coverage bar: the distinct outlets that covered a story, split by one
 * dimension. Plain HTML (no chart library): a 2px surface gap between segments, a hatched fill
 * for unrated outlets, and the numbers always printed next to the bar so colour is never the
 * only carrier of meaning. Each segment has a hover title.
 */
export function CoverageBar({
  parts,
  size = "md",
  caption,
  labels = "nonzero",
  unit = ["outlet", "outlets"],
}: {
  parts: Segment[];
  size?: "sm" | "md";
  /** Accessible name prefix, e.g. "Coverage by perspective". */
  caption: string;
  /** "all": every category, so a 0% side is visible (hatched unrated/other only when > 0). */
  labels?: "nonzero" | "all" | "none";
  /** What one unit of a segment counts (singular, plural). */
  unit?: [string, string];
}) {
  const total = parts.reduce((sum, p) => sum + p.value, 0);
  if (!total) return <span className="rank-meta">No coverage data</span>;
  const shown = parts.filter((p) => p.value > 0);
  const text = shown
    .map((p) => `${p.label}: ${p.value} ${p.value === 1 ? unit[0] : unit[1]} (${formatPercent(p.value / total)})`)
    .join(", ");
  return (
    <div className={`coverage coverage--${size}`}>
      <div className="coverage__bar" role="img" aria-label={`${caption}. ${text}.`}>
        {shown.map((p) => (
          <span
            key={p.key}
            className={`coverage__seg ${p.hatched ? "seg--hatched" : ""}`}
            style={{ flexGrow: p.value, background: p.color }}
            title={`${p.label}: ${p.value} (${formatPercent(p.value / total)})`}
          />
        ))}
      </div>
      {labels !== "none" && (
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

/** A story's coverage through one lens. */
export function StoryCoverage({
  coverage,
  lens,
  size = "md",
  unit,
}: {
  coverage: Coverage;
  lens: Lens;
  size?: "sm" | "md";
  unit?: [string, string];
}) {
  return (
    <CoverageBar
      parts={segments(coverage, lens)}
      size={size}
      caption={`Coverage by ${LENS_LABEL[lens].toLowerCase()}`}
      labels={lens === "perspective" ? "all" : "nonzero"}
      unit={unit}
    />
  );
}

export const LENSES: Lens[] = ["perspective", "region", "ownership", "factuality"];

export function LensPicker({ lens, onChange }: { lens: Lens; onChange: (lens: Lens) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Split coverage by">
      {LENSES.map((l) => (
        <button key={l} type="button" aria-pressed={lens === l} onClick={() => onChange(l)}>
          {LENS_LABEL[l]}
        </button>
      ))}
    </div>
  );
}
