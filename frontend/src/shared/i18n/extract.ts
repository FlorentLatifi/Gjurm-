/**
 * Finding interface strings in source code, for the build (vite.config.ts hands every module
 * the Albanian of the strings it uses) and for the test that keeps the catalog complete.
 * Interface text is a string literal passed to t() or tn(), or a value in a labels({...}) table.
 */
const LITERAL = String.raw`"((?:[^"\\]|\\.)*)"`;
const T_CALL = new RegExp(String.raw`\bt\(\s*${LITERAL}`, "g");
const TN_CALL = new RegExp(String.raw`\btn\(\s*[^,]+,\s*${LITERAL},\s*${LITERAL}`, "g");
const LABELS = /\blabels\(\{([\s\S]*?)\}\)/g;
const LABEL_VALUE = new RegExp(String.raw`:\s*${LITERAL}`, "g");

const unquote = (s: string): string => JSON.parse(`"${s}"`) as string;

export function interfaceStrings(code: string): string[] {
  const found = new Set<string>();
  for (const m of code.matchAll(T_CALL)) found.add(unquote(m[1]!));
  for (const m of code.matchAll(TN_CALL)) {
    found.add(unquote(m[1]!));
    found.add(unquote(m[2]!));
  }
  for (const block of code.matchAll(LABELS)) {
    for (const m of block[1]!.matchAll(LABEL_VALUE)) found.add(unquote(m[1]!));
  }
  return [...found];
}

/** The catalog object of an sq.ts source: plain data, so it is evaluated as an object literal. */
export function parseCatalog(source: string): Record<string, string> {
  const body = /export const sq[^=]*=\s*(\{[\s\S]*\});?\s*$/.exec(source)?.[1];
  if (!body) throw new Error("sq.ts: expected `export const sq: Record<string, string> = { … };`");
  return new Function(`return (${body});`)() as Record<string, string>;
}
