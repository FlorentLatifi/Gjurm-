import type { Coverage, StoryArticle } from "@/shared/api/types";
import { biasGroup, type Lens, REGION_ORDER, type Segment, segments } from "@/shared/model/ratings";

/** Which coverage-bar segment an article's outlet falls in, for one lens. */
export function groupOf(a: StoryArticle, lens: Lens): string {
  if (lens === "perspective") return biasGroup(a.source_bias);
  if (lens === "region") return REGION_ORDER.includes(a.source_country) ? a.source_country : "other";
  if (lens === "ownership") return a.source_ownership;
  const f = a.source_factuality;
  return f === "very_high" || f === "high" ? "high" : f === "very_low" || f === "low" ? "low" : f;
}

/** The story's segments for a lens, by key: the colour and label each article's mark uses. */
export function segmentsByKey(coverage: Coverage, lens: Lens): Map<string, Segment> {
  return new Map(segments(coverage, lens).map((s) => [s.key, s]));
}

/** A mark's colour: the segment's, or the unrated ink where the bar would be hatched. */
export function markColor(seg: Segment | undefined): string {
  return !seg || seg.hatched ? "var(--unrated-ink)" : seg.color;
}
