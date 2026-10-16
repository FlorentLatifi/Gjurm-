import { sqNumber } from "./albanian";

/**
 * The interface language. Albanian is the default (the site is for Albanian readers); English
 * is a per-browser choice. Interface text is written in English in the code and looked up in
 * the Albanian catalog (sq.ts); src/test/i18n.test.ts fails when a string has no translation.
 *
 * The catalog is not loaded whole: at build time each module is given the Albanian of the
 * strings it uses (vite.config.ts, `translations`), which it adds here when it loads. So every
 * page's code carries its own text, and the first page load only the text it shows.
 *
 * The language is module state, not React state: formatting helpers outside components read it
 * too. Changing it remounts the app (app/LanguageRoot), so every component renders anew.
 */
export type Lang = "sq" | "en";
export const LANGS: readonly Lang[] = ["sq", "en"];
export const DEFAULT_LANG: Lang = "sq";

let current: Lang = DEFAULT_LANG;
const albanian: Record<string, string> = {};

/** Called by every module that shows interface text, with the Albanian of its strings. */
export function addTranslations(entries: Record<string, string>): void {
  Object.assign(albanian, entries);
}

export function isLang(value: unknown): value is Lang {
  return value === "sq" || value === "en";
}

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang): void {
  current = lang;
  document.documentElement.lang = lang;
}

/** BCP 47 locale for Intl formatting (Albanian numbers and dates: ./albanian). */
export function locale(): string {
  return current === "sq" ? "sq-AL" : "en-GB";
}

type Vars = Record<string, string | number>;

function fill(template: string, vars?: Vars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in vars ? String(vars[key]) : whole));
}

/** Translate interface text written in English; `{name}` placeholders are filled from `vars`. */
export function t(text: string, vars?: Vars): string {
  return fill(current === "sq" ? (albanian[text] ?? text) : text, vars);
}

/**
 * A counted phrase: `one` when n is 1, else `other`; `{n}` is the formatted number.
 * Albanian, like English, has one singular and one plural form.
 */
export function tn(n: number, one: string, other: string, vars?: Vars): string {
  const formatted = current === "sq" ? sqNumber(n) : new Intl.NumberFormat(locale()).format(n);
  return t(n === 1 ? one : other, { ...vars, n: formatted });
}

/**
 * Marks English text as an interface string to be translated later, where it is stored before
 * it is shown (label tables). Returns it unchanged; render it with t().
 */
export function msg<T extends string>(text: T): T {
  return text;
}

/**
 * A label table whose values are English interface strings, read translated: each property is
 * looked up when it is read, so a table defined once at module load follows the language.
 */
export function labels<K extends string>(table: Record<K, string>): Readonly<Record<K, string>> {
  const out = {} as Record<K, string>;
  for (const key of Object.keys(table) as K[]) {
    Object.defineProperty(out, key, { get: () => t(table[key]), enumerable: true });
  }
  return out;
}

/** A name the API gives in both languages (topics): the reader's, or English when it has none. */
export function localName(en: string, sq: string | null | undefined): string;
export function localName(en: string | null, sq: string | null | undefined): string | null;
export function localName(en: string | null, sq: string | null | undefined): string | null {
  return current === "sq" && sq ? sq : en;
}
