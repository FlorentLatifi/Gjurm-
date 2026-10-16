import type { Coverage } from "@/shared/api/types";
import { type Lens, LENS_LABEL, LENSES, segments } from "@/shared/model/ratings";
import { CoverageBar } from "@/ui/CoverageBar";

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
    <div className="segmented" role="group" aria-label="Split coverage by">
      {available.map((l) => (
        <button key={l} type="button" aria-pressed={lens === l} onClick={() => onChange(l)}>
          {LENS_LABEL[l]}
        </button>
      ))}
    </div>
  );
}
