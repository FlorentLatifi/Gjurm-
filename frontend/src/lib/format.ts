const LOCALE = "en-GB";
const TZ = "Europe/Tirane";

const intFmt = new Intl.NumberFormat(LOCALE);
const compactFmt = new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 1 });

export function formatInt(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : intFmt.format(n);
}

export function formatCompact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Math.abs(n) >= 10_000 ? compactFmt.format(n) : intFmt.format(n);
}

export function formatPercent(ratio: number | null | undefined, digits = 0): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return "—";
  return `${(ratio * 100).toFixed(digits)}%`;
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
  if (score === null || score === undefined) return "No data";
  if (score <= -0.15) return "Negative";
  if (score >= 0.15) return "Positive";
  return "Neutral";
}

const dayFmt = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", timeZone: "UTC" });
const dayLongFmt = new Intl.DateTimeFormat(LOCALE, {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const dateTimeFmt = new Intl.DateTimeFormat(LOCALE, {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: TZ,
});

/** API days are calendar dates (YYYY-MM-DD); format them without timezone shifts. */
export function formatDay(day: string, long = false): string {
  const d = new Date(`${day}T00:00:00Z`);
  return (long ? dayLongFmt : dayFmt).format(d);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dateTimeFmt.format(new Date(iso));
}

const rtf = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });

export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "never";
  const seconds = (new Date(iso).getTime() - now.getTime()) / 1000;
  const abs = Math.abs(seconds);
  if (abs < 60) return rtf.format(Math.round(seconds), "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
  return rtf.format(Math.round(seconds / 86400), "day");
}

export const ENTITY_TYPE_LABEL: Record<string, string> = {
  person: "Person",
  organization: "Organisation",
  location: "Place",
};

export const EVENT_TYPE_LABEL: Record<string, string> = {
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
};

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
