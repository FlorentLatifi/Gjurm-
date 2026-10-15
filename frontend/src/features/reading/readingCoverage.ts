import type { BiasGroup, Coverage, SourceStat } from "@/shared/api/types";
import { biasGroup } from "@/shared/model/ratings";
import type { ReadEntry } from "@/stores/reading";

/** What this reader opened, as one Coverage record (the same shape as a story's). */
export function readingCoverage(entries: ReadEntry[], sources: Map<string, SourceStat>): Coverage {
  const cov: Coverage = {
    bias: { left: 0, center: 0, right: 0, unrated: 0 },
    factuality: { high: 0, mixed: 0, low: 0, unrated: 0 },
    ownership: {},
    region: {},
  };
  for (const e of entries) {
    const s = sources.get(e.s);
    cov.bias[s ? biasGroup(s.bias) : "unrated"] += 1;
    const f = s?.factuality ?? "unrated";
    const fg = f === "very_high" || f === "high" ? "high" : f === "very_low" || f === "low" ? "low" : f;
    cov.factuality[fg] += 1;
    const o = s?.ownership ?? "unknown";
    cov.ownership[o] = (cov.ownership[o] ?? 0) + 1;
    const c = s?.country ?? "other";
    cov.region[c] = (cov.region[c] ?? 0) + 1;
  }
  return cov;
}

/** The side this reader sees least of, if their rated reading leans clearly one way. */
export function missingSide(cov: Coverage): Exclude<BiasGroup, "unrated" | "center"> | null {
  const rated = cov.bias.left + cov.bias.center + cov.bias.right;
  if (rated < 5) return null;
  if (cov.bias.left / rated >= 0.6 && cov.bias.right / rated <= 0.15) return "right";
  if (cov.bias.right / rated >= 0.6 && cov.bias.left / rated <= 0.15) return "left";
  return null;
}
