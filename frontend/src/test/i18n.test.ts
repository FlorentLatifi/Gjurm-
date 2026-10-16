import { getLang, labels, setLang, t, tn } from "@/shared/i18n";
import { interfaceStrings as extract, parseCatalog } from "@/shared/i18n/extract";
import { sq } from "@/shared/i18n/sq";
import catalogSource from "@/shared/i18n/sq.ts?raw";
import {
  formatCompact,
  formatDateTime,
  formatDay,
  formatDecimal,
  formatInt,
  formatPercent,
  formatRelative,
} from "@/shared/lib/format";

// Every source file's text (Vite reads them; tests and generated files are left out below).
const files = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/test/**", "!/src/**/*.test.{ts,tsx}", "!/src/**/*.gen.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** The English interface strings in the code, with the first file that uses each. */
function interfaceStrings(): Map<string, string> {
  const found = new Map<string, string>();
  for (const [where, code] of Object.entries(files)) {
    for (const text of extract(code)) if (!found.has(text)) found.set(text, where);
  }
  return found;
}

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("Albanian interface", () => {
  afterEach(() => setLang("en"));

  it("has a translation for every interface string, with its placeholders", () => {
    const strings = interfaceStrings();
    const missing = [...strings].filter(([en]) => !(en in sq)).map(([en, file]) => `${file}: ${JSON.stringify(en)}`);
    expect(missing, `untranslated:\n${missing.join("\n")}`).toEqual([]);
    // Every placeholder is filled, and none is unknown; a count may go unsaid ("dita e fundit").
    const mismatched = [...strings.keys()].filter((en) => {
      if (!(en in sq)) return false;
      const want = placeholders(en);
      const got = placeholders(sq[en]!);
      return got.some((p) => !want.includes(p)) || want.some((p) => p !== "n" && !got.includes(p));
    });
    expect(mismatched).toEqual([]);
  });

  it("reads the catalog the way the build does", () => {
    expect(parseCatalog(catalogSource)).toEqual(sq);
  });

  it("keeps no translations the code no longer uses", () => {
    const strings = interfaceStrings();
    expect(Object.keys(sq).filter((en) => !strings.has(en))).toEqual([]);
  });

  it("translates text, counts and label tables, and formats dates in the reader's language", () => {
    const table = labels({ left: "Left" });
    setLang("sq");
    expect(getLang()).toBe("sq");
    expect(document.documentElement.lang).toBe("sq");
    expect(table.left).toBe(sq["Left"]);
    expect(tn(1, "{n} outlet", "{n} outlets")).toBe(sq["{n} outlet"]!.replace("{n}", "1"));
    expect(tn(5, "{n} outlet", "{n} outlets")).toBe(sq["{n} outlets"]!.replace("{n}", "5"));
    expect(formatRelative(new Date(Date.now() - 2 * 3600_000).toISOString())).toMatch(/orë/);
    setLang("en");
    expect(table.left).toBe("Left");
    expect(t("Untranslated text {x}", { x: 1 })).toBe("Untranslated text 1");
  });

  it("writes Albanian numbers and dates itself, since Chromium browsers have no Albanian locale data", () => {
    setLang("sq");
    const now = new Date("2026-10-16T12:00:00Z");
    const ago = (seconds: number) => formatRelative(new Date(now.getTime() - seconds * 1000).toISOString(), now);
    expect(formatInt(1234567)).toBe("1\u00a0234\u00a0567");
    expect(formatDecimal(12.5)).toBe("12,5");
    expect(formatPercent(0.1234, 1)).toBe("12,3%");
    expect(formatCompact(12_900)).toBe("12,9 mijë");
    expect(tn(1200, "{n} article", "{n} articles")).toBe("1\u00a0200 artikuj");
    expect(formatDay("2026-10-14")).toBe("14 tet");
    expect(formatDay("2026-10-14", true)).toBe("Mër, 14 tet 2026");
    expect(formatDateTime("2026-10-14T13:06:00Z")).toBe("14 tet, 15:06"); // Tirana, summer time
    expect(formatDateTime("2026-12-01T08:30:00Z")).toBe("1 dhj, 09:30");
    expect(ago(20)).toBe("tani");
    expect(ago(60)).toBe("1 minutë më parë");
    expect(ago(5 * 60)).toBe("5 minuta më parë");
    expect(ago(2 * 3600)).toBe("2 orë më parë");
    expect(ago(30 * 3600)).toBe("dje");
    expect(ago(3 * 86400)).toBe("3 ditë më parë");
    expect(ago(-3600)).toBe("për 1 orë");
  });
});
