import type { BiasGroup, BiasRating, Coverage, FactualityRating, OwnershipType } from "@/shared/api/types";
import { labels, t } from "@/shared/i18n";

/**
 * Labels and colours for the coverage dimensions (mirrors backend gjurme/sources/ratings.py).
 * Perspective is a diverging scale (blue ← gray → red, ADR-011 tokens); region and ownership are
 * categorical slots assigned to a fixed entity, never by rank; "unrated"/"unknown" is a hatched
 * neutral so it can never be mistaken for the center.
 */
export const BIAS_LABEL: Readonly<Record<BiasRating, string>> = labels({
  left: "Left",
  lean_left: "Lean left",
  center: "Center",
  lean_right: "Lean right",
  right: "Right",
  unrated: "Unrated",
});

export const BIAS_GROUP_LABEL: Readonly<Record<BiasGroup, string>> = labels({
  left: "Left",
  center: "Center",
  right: "Right",
  unrated: "Unrated",
});

export const BIAS_GROUP_COLOR: Record<BiasGroup, string> = {
  left: "var(--bias-left)",
  center: "var(--bias-center)",
  right: "var(--bias-right)",
  unrated: "var(--unrated)",
};

export function biasGroup(bias: BiasRating): BiasGroup {
  if (bias === "left" || bias === "lean_left") return "left";
  if (bias === "lean_right" || bias === "right") return "right";
  return bias === "center" ? "center" : "unrated";
}

export const FACTUALITY_LABEL: Readonly<Record<FactualityRating, string>> = labels({
  very_high: "Very high",
  high: "High",
  mixed: "Mixed",
  low: "Low",
  very_low: "Very low",
  unrated: "Unrated",
});

export const FACTUALITY_GROUP_LABEL = labels({ high: "High", mixed: "Mixed", low: "Low", unrated: "Unrated" });
/** A factuality group named on its own, as in a legend. */
const FACTUALITY_SEGMENT_LABEL = labels({
  high: "High factuality",
  mixed: "Mixed factuality",
  low: "Low factuality",
  unrated: "Unrated factuality",
});
export const FACTUALITY_GROUP_COLOR = {
  high: "var(--fact-high)",
  mixed: "var(--fact-mixed)",
  low: "var(--fact-low)",
  unrated: "var(--unrated)",
};

export const OWNERSHIP_LABEL: Readonly<Record<OwnershipType, string>> = labels({
  private: "Private company",
  media_group: "Media group",
  public: "Public broadcaster",
  state: "State-controlled",
  public_international: "International public media",
  nonprofit: "Non-profit",
  unknown: "Unknown",
});

/** Fixed slot per ownership type (categorical slots 1–6 in order; unknown is hatched). */
export const OWNERSHIP_ORDER: OwnershipType[] = [
  "private",
  "media_group",
  "public",
  "public_international",
  "nonprofit",
  "state",
  "unknown",
];
const OWNERSHIP_COLOR: Record<OwnershipType, string> = {
  private: "var(--cat-1)",
  media_group: "var(--cat-2)",
  public: "var(--cat-3)",
  public_international: "var(--cat-4)",
  nonprofit: "var(--cat-5)",
  state: "var(--cat-6)",
  unknown: "var(--unrated)",
};

export const COUNTRY_LABEL: Readonly<Record<string, string>> = labels({
  XK: "Kosovo",
  AL: "Albania",
  MK: "North Macedonia",
  ME: "Montenegro",
  RS: "Serbia",
  REG: "Regional / international",
});
/** The countries GJURMË follows outlets in, each with its own fixed slot; others fold together. */
export const REGION_ORDER = ["XK", "AL", "MK", "REG"];
const REGION_COLOR: Record<string, string> = {
  XK: "var(--cat-1)",
  AL: "var(--cat-2)",
  MK: "var(--cat-3)",
  REG: "var(--cat-4)",
};

export function countryLabel(code: string): string {
  return COUNTRY_LABEL[code] ?? code;
}

export interface Segment {
  key: string;
  label: string;
  value: number;
  color: string;
  /** Hatched fill: "unrated" / "unknown" / "other", never confused with a real category. */
  hatched?: boolean;
}

export type Lens = "perspective" | "region" | "ownership" | "factuality";
export const LENS_LABEL: Readonly<Record<Lens, string>> = labels({
  perspective: "Perspective",
  region: "Region",
  ownership: "Ownership",
  factuality: "Factuality",
});

/** The segments of one coverage dimension, in the dimension's fixed order. */
export function segments(coverage: Coverage, lens: Lens): Segment[] {
  if (lens === "perspective") {
    return (["left", "center", "right", "unrated"] as BiasGroup[]).map((g) => ({
      key: g,
      label: BIAS_GROUP_LABEL[g],
      value: coverage.bias[g] ?? 0,
      color: BIAS_GROUP_COLOR[g],
      hatched: g === "unrated",
    }));
  }
  if (lens === "factuality") {
    return (["high", "mixed", "low", "unrated"] as const).map((g) => ({
      key: g,
      label: FACTUALITY_SEGMENT_LABEL[g],
      value: coverage.factuality[g] ?? 0,
      color: FACTUALITY_GROUP_COLOR[g],
      hatched: g === "unrated",
    }));
  }
  if (lens === "ownership") {
    return OWNERSHIP_ORDER.map((o) => ({
      key: o,
      label: OWNERSHIP_LABEL[o],
      value: coverage.ownership[o] ?? 0,
      color: OWNERSHIP_COLOR[o],
      hatched: o === "unknown",
    }));
  }
  const other = Object.entries(coverage.region)
    .filter(([code]) => !REGION_ORDER.includes(code))
    .reduce((sum, [, n]) => sum + n, 0);
  return [
    ...REGION_ORDER.map((code) => ({
      key: code,
      label: countryLabel(code),
      value: coverage.region[code] ?? 0,
      color: REGION_COLOR[code]!,
    })),
    { key: "other", label: t("Other"), value: other, color: "var(--unrated)", hatched: true },
  ];
}

/** True when no outlet in these stories has a perspective rating yet. */
export function noneRated(coverages: Coverage[]): boolean {
  return coverages.every((c) => c.bias.left + c.bias.center + c.bias.right === 0);
}

export const LENSES: Lens[] = ["perspective", "region", "ownership", "factuality"];

/**
 * The lenses with something to show for these stories. Perspective and factuality are editorial
 * ratings an outlet may not have yet; a bar in which every outlet is "unrated" says nothing, so
 * those lenses appear once any outlet in view is rated. Region and ownership always apply.
 */
export function availableLenses(coverages: Coverage[]): Lens[] {
  const any = (count: (c: Coverage) => number) => coverages.some((c) => count(c) > 0);
  return LENSES.filter((lens) => {
    if (lens === "perspective") return any((c) => c.bias.left + c.bias.center + c.bias.right);
    if (lens === "factuality") return any((c) => c.factuality.high + c.factuality.mixed + c.factuality.low);
    return true;
  });
}

export function blindspotLabel(b: { kind: string; missing: string }): string {
  if (b.kind === "perspective") {
    return b.missing === "left"
      ? t("Blindspot: few left-leaning outlets covered this")
      : t("Blindspot: few right-leaning outlets covered this");
  }
  return t("Blindspot: no outlet from {country} covered this", { country: countryLabel(b.missing) });
}
