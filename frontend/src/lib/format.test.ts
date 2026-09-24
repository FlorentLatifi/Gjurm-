import { buildQuery } from "../api/client";
import {
  formatChange,
  formatCompact,
  formatDay,
  formatInt,
  formatPercent,
  formatRelative,
  formatScore,
  hasComparableHistory,
  hostOf,
  safeHref,
  toneLabel,
} from "./format";

describe("number formatting", () => {
  it("formats integers and compact numbers", () => {
    expect(formatInt(1234567)).toBe("1,234,567");
    expect(formatInt(null)).toBe("—");
    expect(formatCompact(9999)).toBe("9,999");
    expect(formatCompact(12_900).toLowerCase()).toBe("12.9k");
  });

  it("formats percentages and signed changes with a real minus sign", () => {
    expect(formatPercent(0.1234, 1)).toBe("12.3%");
    expect(formatPercent(Number.NaN)).toBe("—");
    expect(formatChange(0.42)).toBe("+42%");
    expect(formatChange(-0.08)).toBe("−8%");
    expect(formatChange(0.001)).toBe("±0%");
    expect(formatChange(null)).toBe("—");
  });

  it("never prints signed zero for tone scores", () => {
    expect(formatScore(0.5)).toBe("+0.50");
    expect(formatScore(-0.25)).toBe("−0.25");
    expect(formatScore(-0.001)).toBe("0.00");
    expect(formatScore(0.004)).toBe("0.00");
    expect(formatScore(null)).toBe("—");
  });

  it("labels tone with the same thresholds as the prompt", () => {
    expect(toneLabel(-0.2)).toBe("Negative");
    expect(toneLabel(0.1)).toBe("Neutral");
    expect(toneLabel(0.15)).toBe("Positive");
    expect(toneLabel(null)).toBe("No data");
  });
});

describe("dates", () => {
  it("formats API calendar days without timezone drift", () => {
    expect(formatDay("2026-09-24")).toBe("24 Sept");
    expect(formatDay("2026-01-01", true)).toContain("2026");
  });

  it("formats relative times", () => {
    const now = new Date("2026-09-24T12:00:00Z");
    expect(formatRelative("2026-09-24T11:58:00Z", now)).toBe("2 minutes ago");
    expect(formatRelative("2026-09-24T09:00:00Z", now)).toBe("3 hours ago");
    expect(formatRelative(null, now)).toBe("never");
  });
});

describe("link safety", () => {
  it("only allows http(s) URLs as hrefs", () => {
    expect(safeHref("https://telegrafi.com/lajm")).toBe("https://telegrafi.com/lajm");
    expect(safeHref("javascript:alert(1)")).toBeUndefined();
    expect(safeHref("data:text/html,<b>x</b>")).toBeUndefined();
    expect(safeHref("not a url")).toBeUndefined();
  });

  it("extracts a display host", () => {
    expect(hostOf("https://www.koha.net/lajme/1")).toBe("koha.net");
    expect(hostOf("::")).toBe("");
  });
});

describe("comparable history", () => {
  const rows = [
    { cur: 10, prev: 8 },
    { cur: 5, prev: 1 },
  ];
  it("allows period comparison only when the previous window has data", () => {
    expect(hasComparableHistory(rows, (r) => r.cur, (r) => r.prev)).toBe(true);
    expect(hasComparableHistory(rows, (r) => r.cur, () => 1)).toBe(false);
    expect(hasComparableHistory([], (r: { cur: number }) => r.cur, () => 0)).toBe(false);
  });
});

describe("query strings", () => {
  it("drops empty values, repeats arrays and sorts keys (stable cache keys)", () => {
    expect(buildQuery({ q: "zgjedhjet", source: ["koha", "kallxo"], empty: "", none: undefined, days: 7 })).toBe(
      "?days=7&q=zgjedhjet&source=koha&source=kallxo",
    );
    expect(buildQuery({})).toBe("");
  });
});
