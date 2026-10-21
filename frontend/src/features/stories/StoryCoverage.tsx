import type { Coverage } from "@/shared/api/types";
import { formatPercent } from "@/shared/lib/format";
import { leadingSegment, type Lens, LENS_LABEL, LENSES, segments } from "@/shared/model/ratings";
import { CoverageBar } from "@/ui/CoverageBar";
import { labels, t, tn } from "@/shared/i18n";

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
}: {
  coverage: Coverage;
  lens: Lens;
  size?: "xs" | "sm" | "md" | "lg";
  unit?: (n: number) => string;
  labels?: "nonzero" | "all" | "none" | "inside";
}) {
  return (
    <CoverageBar
      parts={segments(coverage, lens)}
      size={size}
      caption={COVERAGE_BY[lens]}
      labels={shown ?? (lens === "perspective" ? "all" : "nonzero")}
      unit={unit}
    />
  );
}

/** Ground News' one-line coverage: "45% Center coverage: 188 sources". */
export function coverageSentence(coverage: Coverage, lens: Lens, sources: number): string {
  const outlets = tn(sources, "{n} outlet", "{n} outlets");
  const lead = leadingSegment(segments(coverage, lens));
  if (!lead) return t("Coverage: {outlets}", { outlets });
  return t("{share} {side} coverage: {outlets}", {
    share: formatPercent(lead.share),
    side: lead.segment.label,
    outlets,
  });
}

/** A story row's coverage: the short bar and its sentence. */
export function CoverageLine({ coverage, lens, sources }: { coverage: Coverage; lens: Lens; sources: number }) {
  return (
    <div className="coverage-line">
      <StoryCoverage coverage={coverage} lens={lens} size="xs" labels="none" />
      <span>{coverageSentence(coverage, lens, sources)}</span>
    </div>
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
