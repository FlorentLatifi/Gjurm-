import { getLang, labels, locale, t } from "@/shared/i18n";
import { sqCompact, sqDateTime, sqDay, sqNumber, sqRelative } from "@/shared/i18n/albanian";

const TZ = "Europe/Tirane";

/** Intl formatters per locale and options, made once each (the language can change). */
const formatters = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat | Intl.RelativeTimeFormat>();
function cached<F extends Intl.NumberFormat | Intl.DateTimeFormat | Intl.RelativeTimeFormat>(
  name: string,
  make: (locale: string) => F,
): F {
  const key = `${locale()}:${name}`;
  let f = formatters.get(key) as F | undefined;
  if (!f) {
    f = make(locale());
    formatters.set(key, f);
  }
  return f;
}
const intFmt = () => cached("int", (l) => new Intl.NumberFormat(l));
const compactFmt = () => cached("compact", (l) => new Intl.NumberFormat(l, { notation: "compact", maximumFractionDigits: 1 }));

// Albanian is formatted by shared/i18n/albanian: browsers without Albanian locale data (all
// Chromium ones) would otherwise show US English.
const sq = () => getLang() === "sq";

export function formatInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return sq() ? sqNumber(n) : intFmt().format(n);
}

export function formatCompact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) < 10_000) return formatInt(n);
  return sq() ? sqCompact(n) : compactFmt().format(n);
}

/** One decimal place, e.g. 12.5 (12,5 in Albanian). */
export function formatDecimal(n: number): string {
  const options = { minimumFractionDigits: 1, maximumFractionDigits: 1 };
  return sq() ? sqNumber(n, options) : cached("decimal1", (l) => new Intl.NumberFormat(l, options)).format(n);
}

export function formatPercent(ratio: number | null | undefined, digits = 0): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return "—";
  const options = { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false };
  const value = sq() ? sqNumber(ratio * 100, options) : cached(`fixed${digits}`, (l) => new Intl.NumberFormat(l, options)).format(ratio * 100);
  return `${value}%`;
}

/** Signed change as a percentage, e.g. +42% / −8%. Uses a real minus sign. */
export function formatChange(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return "—";
  const pct = Math.round(ratio * 100);
  if (pct === 0) return "±0%";
  return `${pct > 0 ? "+" : "−"}${Math.abs(pct)}%`;
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return "—";
  const v = score.toFixed(2);
  if (Math.abs(score) < 0.005) return "0.00"; // never show "+0.00" / "−0.00"
  return score > 0 ? `+${v}` : `−${v.slice(1)}`;
}

export function toneLabel(score: number | null | undefined): string {
  if (score === null || score === undefined) return t("No data");
  if (score <= -0.15) return t("Negative");
  if (score >= 0.15) return t("Positive");
  return t("Neutral");
}

const dayFmt = () => cached("day", (l) => new Intl.DateTimeFormat(l, { day: "numeric", month: "short", timeZone: "UTC" }));
const dayLongFmt = () =>
  cached("dayLong", (l) => new Intl.DateTimeFormat(l, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }));
const dateTimeFmt = () =>
  cached("dateTime", (l) => new Intl.DateTimeFormat(l, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: TZ,
  }));

/** API days are calendar dates (YYYY-MM-DD); format them without timezone shifts. */
export function formatDay(day: string, long = false): string {
  const d = new Date(`${day}T00:00:00Z`);
  if (sq()) return sqDay(d, long);
  return (long ? dayLongFmt() : dayFmt()).format(d);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return sq() ? sqDateTime(new Date(iso), TZ) : dateTimeFmt().format(new Date(iso));
}

const rtf = () => cached("relative", (l) => new Intl.RelativeTimeFormat(l, { numeric: "auto" }));

export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return t("never");
  const seconds = (new Date(iso).getTime() - now.getTime()) / 1000;
  if (sq()) return sqRelative(seconds);
  const abs = Math.abs(seconds);
  if (abs < 60) return rtf().format(Math.round(seconds), "second");
  if (abs < 3600) return rtf().format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return rtf().format(Math.round(seconds / 3600), "hour");
  return rtf().format(Math.round(seconds / 86400), "day");
}

export const ENTITY_TYPE_LABEL: Readonly<Record<string, string>> = labels({
  person: "Person",
  organization: "Organisation",
  location: "Place",
});

export const EVENT_TYPE_LABEL: Readonly<Record<string, string>> = labels({
  statement: "Statement",
  policy_decision: "Policy decision",
  election_event: "Election event",
  protest: "Protest",
  investigation_arrest: "Investigation / arrest",
  court_ruling: "Court ruling",
  incident_accident: "Incident / accident",
  diplomatic_meeting: "Diplomatic meeting",
  report_data: "Report / data",
  sports_result: "Sports result",
  cultural_event: "Cultural event",
  other: "Other",
});

/** Only http(s) links may be rendered as hrefs (defence in depth; the API validates too). */
export function safeHref(url: string): string | undefined {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : undefined;
  } catch {
    return undefined;
  }
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/**
 * Period-over-period changes are only meaningful when the previous window actually contains
 * data. If the previous period holds less than half the current volume (typically: the dataset
 * is younger than two windows), percentages would be misleadingly huge — show "—" instead.
 */
export function hasComparableHistory<T>(rows: T[], current: (r: T) => number, previous: (r: T) => number): boolean {
  const cur = rows.reduce((s, r) => s + current(r), 0);
  const prev = rows.reduce((s, r) => s + previous(r), 0);
  return cur > 0 && prev >= 0.5 * cur;
}

/**
 * The AI summary, or null. Keyword-rule analysis stores a placeholder ("[headline, no AI
 * summary] …" — the headline again), which must never be shown as if it were a summary.
 */
export function realSummary(summary: string | null | undefined): string | null {
  return summary && !summary.startsWith("[headline") ? summary : null;
}

/**
 * The AI summary to show, in the reader's language when it exists: articles analysed with
 * prompt v1.2 or later have an Albanian one; older ones only the English.
 */
export function summaryFor(item: {
  summary_en: string | null;
  summary_sq: string | null;
}): { text: string; lang: "sq" | "en" } | null {
  const albanian = getLang() === "sq" ? realSummary(item.summary_sq) : null;
  if (albanian) return { text: albanian, lang: "sq" };
  const english = realSummary(item.summary_en);
  return english ? { text: english, lang: "en" } : null;
}
