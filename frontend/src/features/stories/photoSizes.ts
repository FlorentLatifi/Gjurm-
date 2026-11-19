/**
 * Smaller copies of an outlet's photo, from the outlet's own image server (ADR-030, amended
 * 2026-11-19). A feed names one size, often 1,000–1,500 px wide, while a story row shows it at
 * 84 px on a phone and at most 236 px on a wide screen (the lead story at most 432 px). Some
 * outlets' servers make any width on request, or keep the copies WordPress made at upload; for
 * those the <img> gets a srcset and the browser takes the smallest that fills the box. GJURMË
 * still never downloads, resizes or stores a photo: every address here is the outlet's own.
 *
 * Each rule was checked against the outlet's server on 2026-11-19 (the same photo, full and small):
 *   Telegrafi  `width=980` 63 KB → `width=320` 11.7 KB (any width, PNG too)
 *   KOHA       original 71 KB → `w=320` 19 KB; a `w` above the photo's own width gives the photo
 *   Ekonomia   `-1333x1000.jpg` 266 KB → `-300x225.jpg` 20 KB (5 of 5 photos; its 768 px copy is
 *              missing for some, so only the 300 px one is used)
 * Zëri's server ignores width parameters, so its photos stay as the feed gives them. A copy that
 * fails to load falls back to the feed's own address (Cover in StoryCard.tsx).
 */

type Rule = (url: URL) => string | null;

const SMALL = [320, 640];

function withParam(url: URL, name: string, value: number): string {
  const copy = new URL(url.href);
  copy.searchParams.set(name, String(value));
  return copy.href;
}

/** Telegrafi's media library (`/media-library/image.jpg?id=…&width=980`) answers any width. */
const telegrafi: Rule = (url) => {
  const given = Number(url.searchParams.get("width"));
  if (!url.pathname.startsWith("/media-library/") || !Number.isInteger(given) || given <= 0) return null;
  const smaller = SMALL.filter((w) => w < given);
  if (!smaller.length) return null;
  return [...smaller.map((w) => `${withParam(url, "width", w)} ${w}w`), `${url.href} ${given}w`].join(", ");
};

/**
 * KOHA's image server (`resources.koha.net/images/…?q=80`) scales down to `w`, never up. The feed's
 * address names no width, so the full photo is offered as 1280w: chosen only where a box needs
 * more than 640 px, as every photo was before.
 */
const koha: Rule = (url) => {
  if (!url.pathname.startsWith("/images/") || url.searchParams.has("w")) return null;
  return [...SMALL.map((w) => `${withParam(url, "w", w)} ${w}w`), `${url.href} 1280w`].join(", ");
};

/**
 * WordPress keeps a 300 px wide copy of each upload, named with its size: `photo-300x225.jpg`, the
 * height to the photo's own ratio, rounded as PHP rounds. Only for an address that names its own
 * size (`photo-1333x1000.jpg`), so the copy's height can be worked out.
 */
const wordpress: Rule = (url) => {
  const m = /^(\/wp-content\/uploads\/.+)-(\d+)x(\d+)(\.(?:jpe?g|png|webp))$/i.exec(url.pathname);
  if (!m || url.search) return null;
  const [, stem, w, h, ext] = m;
  const width = Number(w);
  const height = Number(h);
  if (width < 600 || height <= 0) return null;
  const small = new URL(url.href);
  small.pathname = `${stem}-300x${Math.round((300 * height) / width)}${ext}`;
  return `${small.href} 300w, ${url.href} ${width}w`;
};

const RULES: Record<string, Rule> = {
  "telegrafi.com": telegrafi,
  "resources.koha.net": koha,
  "ekonomiaonline.com": wordpress,
};

/** A srcset of the outlet's own sizes of this photo, or undefined when its server offers none. */
export function outletSizes(src: string): string | undefined {
  let url: URL;
  try {
    url = new URL(src);
  } catch {
    return undefined;
  }
  if (url.protocol !== "https:") return undefined;
  return RULES[url.hostname]?.(url) ?? undefined;
}

/** How wide each cover is drawn (stories.css): what the browser picks a size from. */
export const COVER_SIZES = {
  hero: "(min-width: 900px) 432px, calc(100vw - 32px)",
  row: "(min-width: 900px) 236px, 84px",
} as const;
