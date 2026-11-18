import { Link } from "react-router-dom";

import type { PublicStatus } from "@/shared/api/types";
import { formatPercent, formatRelative } from "@/shared/lib/format";

import { useStatus } from "./api";
import "./system.css";
import { t } from "@/shared/i18n";

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
    data.status === "stale" ? t("Data not updating") : t("Updated {when}", { when: formatRelative(data.last_success_at) });
  return (
    <Link to="/status" className="status-pill" title={`${t("Pipeline status")}: ${text}`}>
      <span className="dot" style={{ background: colour }} aria-hidden="true" />
      <span className="status-pill__text">{text}</span>
    </Link>
  );
}

interface Notice {
  label: string;
  text: string;
  href: string;
}

/** What the site must say about its data before anything else (ADR-018: free mode is honest). */
export function noticeFor(status: PublicStatus | undefined): Notice | null {
  if (!status) return null;
  if (status.demo_data) {
    return {
      label: t("Demo dataset."),
      text: t("Fictional outlets (“… Demo”) and invented names, so the product can be explored without live data."),
      href: "/about",
    };
  }
  const { mode, rule_based_share, front_page } = status.analysis;
  if (mode !== "rules" && mode !== "mixed") return null;
  const rules = formatPercent(rule_based_share ?? 0);
  let text: string;
  if (mode === "rules") {
    text = t("Topics, tone and names are assigned by keyword rules, not by an AI model — treat them as rough indications.");
  } else if (front_page.ai_share === null) {
    text = t("{share} of recent articles were analysed by keyword rules, not by an AI model — treat them as rough indications.", {
      share: rules,
    });
  } else if (front_page.ai_share >= 1) {
    text = t("Every article on the front page was analysed by an AI model; {rules} of all recent articles by keyword rules — treat those as rough indications.", {
      rules,
    });
  } else {
    // Rounded down, so the line never claims more AI than there is (99.6% is not "100%");
    // the epsilon keeps 0.29 at 29% (0.29 * 100 is 28.999… in floating point).
    text = t("{ai} of the front page’s articles were analysed by an AI model, the rest by keyword rules, as were {rules} of all recent articles — treat those as rough indications.", {
      ai: formatPercent(Math.floor(front_page.ai_share * 100 + 1e-9) / 100),
      rules,
    });
  }
  return {
    label: t("Rule-based analysis."),
    text,
    href: "/about#analysis",
  };
}

/**
 * One line (two on a phone) above every page. Its space is held while the status loads, so the
 * page never jumps down when the notice arrives; the label links to the explanation and the full
 * sentence is in the title when the line is clipped.
 */
export function SiteNotice() {
  const { data, isPending } = useStatus();
  if (isPending) return <div className="notice notice--reserved" aria-hidden="true" />;
  const notice = noticeFor(data);
  if (!notice) return null;
  return (
    <p className="notice" role="note" title={`${notice.label} ${notice.text}`}>
      <Link to={notice.href}>
        <strong>{notice.label}</strong>
      </Link>{" "}
      {notice.text}
    </p>
  );
}
