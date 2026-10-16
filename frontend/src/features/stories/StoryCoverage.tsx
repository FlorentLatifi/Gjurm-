import type { Coverage } from "@/shared/api/types";
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
}: {
  coverage: Coverage;
  lens: Lens;
  size?: "sm" | "md";
  unit?: (n: number) => string;
}) {
  return (
    <CoverageBar
      parts={segments(coverage, lens)}
      size={size}
      caption={COVERAGE_BY[lens]}
      labels={lens === "perspective" ? "all" : "nonzero"}
      unit={unit}
    />
  );
}

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
