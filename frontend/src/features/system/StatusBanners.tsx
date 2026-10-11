import { Link } from "react-router-dom";

import { formatRelative } from "@/shared/lib/format";

import { useStatus } from "./api";

export function StatusPill() {
  const { data } = useStatus();
  if (!data) return null;
  const colour =
    data.status === "ok"
      ? "var(--status-good)"
      : data.status === "degraded"
        ? "var(--status-warning)"
        : "var(--status-critical)";
  const text =
    data.status === "stale" ? "Data not updating" : `Updated ${formatRelative(data.last_success_at)}`;
  return (
    <Link to="/status" className="status-pill" title="Pipeline status">
      <span className="dot" style={{ background: colour }} aria-hidden="true" />
      {text}
    </Link>
  );
}

export function DemoBanner() {
  const { data } = useStatus();
  if (!data?.demo_data) return null;
  return (
    <div className="banner" role="note">
      <strong>Demo dataset.</strong> This instance shows synthetic articles from fictional outlets
      (“… Demo”) so the product can be explored without live data. Names of people are invented.
    </div>
  );
}

/** Says plainly when topics, tone and names come from keyword rules rather than an AI model. */
export function AnalysisBanner() {
  const { data } = useStatus();
  if (!data || data.demo_data) return null; // the demo banner already explains the demo data
  const { mode, rule_based_share } = data.analysis;
  if (mode !== "rules" && mode !== "mixed") return null;
  return (
    <div className="banner" role="note">
      <strong>Rule-based analysis.</strong>{" "}
      {mode === "rules"
        ? "Topics, tone and names on this site are currently assigned by keyword rules, not by an AI model."
        : `${Math.round((rule_based_share ?? 0) * 100)}% of recent articles were analysed by keyword rules, not by an AI model.`}{" "}
      Treat them as rough indications. <Link to="/about#analysis">How this works</Link>
    </div>
  );
}
