/**
 * Albanian numbers, dates and relative times, written out here rather than left to Intl:
 * Chrome and the other Chromium browsers ship no Albanian locale data and fall back to US
 * English without a word ("Oct 14, 03:06 PM", "2 days ago", "1,234.5", whose comma an Albanian
 * reader takes for the decimal sign). Conventions follow CLDR's Albanian: a no-break space groups
 * thousands, a comma marks decimals, the clock runs to 24 hours.
 */
const MONTHS = ["jan", "shk", "mar", "pri", "maj", "qer", "korr", "gush", "sht", "tet", "nën", "dhj"];
const WEEKDAYS = ["Die", "Hën", "Mar", "Mër", "Enj", "Pre", "Sht"]; // Date.getUTCDay() order

// Intl's en-US formatter only splits the number into parts; the separators are replaced.
const numberFormats = new Map<string, Intl.NumberFormat>();
export function sqNumber(n: number, options: Intl.NumberFormatOptions = {}): string {
  const key = JSON.stringify(options);
  let fmt = numberFormats.get(key);
  if (!fmt) numberFormats.set(key, (fmt = new Intl.NumberFormat("en-US", options)));
  return fmt
    .formatToParts(n)
    .map((p) => (p.type === "group" ? " " : p.type === "decimal" ? "," : p.value))
    .join("");
}

/** 12 900 → "12,9 mijë"; 2 400 000 → "2,4 mln". */
export function sqCompact(n: number): string {
  const one = { maximumFractionDigits: 1 };
  return Math.abs(n) >= 1_000_000 ? `${sqNumber(n / 1_000_000, one)} mln` : `${sqNumber(n / 1_000, one)} mijë`;
}

/** A calendar day (read in UTC): "14 tet", or "Mër, 14 tet 2026". */
export function sqDay(date: Date, long: boolean): string {
  const short = `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
  return long ? `${WEEKDAYS[date.getUTCDay()]}, ${short} ${date.getUTCFullYear()}` : short;
}

const clocks = new Map<string, Intl.DateTimeFormat>();
/** A moment on the clock of `timeZone`: "14 tet, 15:06". */
export function sqDateTime(date: Date, timeZone: string): string {
  let fmt = clocks.get(timeZone);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat("en-GB", {
      timeZone, day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    });
    clocks.set(timeZone, fmt);
  }
  const part = (type: string) => fmt.formatToParts(date).find((p) => p.type === type)?.value ?? "";
  return `${Number(part("day"))} ${MONTHS[Number(part("month")) - 1]}, ${part("hour")}:${part("minute")}`;
}

const UNITS = [
  { seconds: 86_400, one: "ditë", other: "ditë" },
  { seconds: 3_600, one: "orë", other: "orë" },
  { seconds: 60, one: "minutë", other: "minuta" },
] as const;

/** Time from now, `seconds` negative for the past: "tani", "5 minuta më parë", "dje", "për 2 orë". */
export function sqRelative(seconds: number): string {
  const abs = Math.abs(seconds);
  if (abs < 60) return "tani";
  const unit = UNITS.find((u) => abs >= u.seconds)!;
  const n = Math.round(abs / unit.seconds);
  if (unit.seconds === 86_400 && n === 1) return seconds < 0 ? "dje" : "nesër";
  const amount = `${n} ${n === 1 ? unit.one : unit.other}`;
  return seconds < 0 ? `${amount} më parë` : `për ${amount}`;
}
