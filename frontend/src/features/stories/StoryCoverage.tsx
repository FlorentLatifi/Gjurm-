import type { Coverage, StorySummary } from "@/shared/api/types";
import { type Lens, LENS_LABEL, LENSES, segments } from "@/shared/model/ratings";
import { CoverageBar } from "@/ui/CoverageBar";
import { labels, t } from "@/shared/i18n";

// Whole phrases per lens: in Albanian the lens noun changes its ending after "by" (sipas).
const COVERAGE_BY = labels({
  perspective: "Coverage by perspective",
  region: "Coverage by region",
  ownership: "Coverage by ownership",
  factuality: "Coverage by factuality",
});

/** A story's coverage through one lens. */
export function StoryCoverage({
  coverage,
  lens,
  size = "md",
  unit,
  labels: shown,
  missing,
}: {
  coverage: Coverage;
  lens: Lens;
  size?: "sm" | "md" | "lg";
  unit?: (n: number) => string;
  labels?: "nonzero" | "all" | "none" | "shares";
  /** The story's blindspots: the sides to draw as an empty slot. */
  missing?: StorySummary["blindspots"];
}) {
  return (
    <CoverageBar
      parts={segments(coverage, lens)}
      size={size}
      caption={COVERAGE_BY[lens]}
      labels={shown ?? (lens === "perspective" ? "all" : "nonzero")}
      missing={missingKeys(missing, lens)}
      unit={unit}
    />
  );
}

/** The segments a story's blindspots leave empty in this lens. */
function missingKeys(blindspots: StorySummary["blindspots"] | undefined, lens: Lens): string[] {
  const kind = lens === "perspective" ? "perspective" : lens === "region" ? "region" : null;
  return (blindspots ?? []).filter((b) => b.kind === kind).map((b) => b.missing);
}

/** A story's split in words, counts first: "2 Left · 5 Center · 1 Right". */
export function coverageCounts(coverage: Coverage, lens: Lens): string {
  return segments(coverage, lens)
    .filter((p) => p.value > 0)
    .map((p) => `${p.value} ${p.label}`)
    .join(" · ");
}

/** The lens as a line of words: the chosen one is inked and underlined. */
export function LensPicker({
  lens,
  onChange,
  available = LENSES,
}: {
  lens: Lens;
  onChange: (lens: Lens) => void;
  available?: Lens[];
}) {
  return (
    <div className="segmented" role="group" aria-label={t("Split coverage by")}>
      {available.map((l) => (
        <button key={l} type="button" aria-pressed={lens === l} onClick={() => onChange(l)}>
          {LENS_LABEL[l]}
        </button>
      ))}
    </div>
  );
}
