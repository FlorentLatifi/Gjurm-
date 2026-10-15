/**
 * Recovery from a page's code failing to load. After a deploy, an open tab still runs the old
 * build and asks for chunks that no longer exist (the server answers 404, see the Caddyfile);
 * offline, any chunk can fail. Reloading once picks up the current build; the timestamp guard
 * makes sure a chunk that keeps failing shows an error instead of reloading in a loop.
 */
const KEY = "gjurme-chunk-reload";
const GUARD_MS = 10_000;

const PATTERNS = [
  /Failed to fetch dynamically imported module/i, // Chromium
  /error loading dynamically imported module/i, // Firefox
  /Importing a module script failed/i, // Safari
  /Unable to preload CSS/i, // Vite's preload helper
];

export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return PATTERNS.some((p) => p.test(message));
}

/**
 * Reloads the page unless it already reloaded for this reason in the last few seconds.
 * Returns whether a reload was started. Without session storage there is no loop guard, so it
 * does not reload at all.
 */
export function reloadOnce(reload: () => void = () => window.location.reload(), now = Date.now()): boolean {
  try {
    const last = Number(sessionStorage.getItem(KEY));
    if (last && now - last < GUARD_MS) return false;
    sessionStorage.setItem(KEY, String(now));
  } catch {
    return false;
  }
  reload();
  return true;
}

/** Vite reports failed preloads of a chunk's dependencies with this event. */
export function installPreloadRecovery() {
  window.addEventListener("vite:preloadError", () => {
    reloadOnce();
  });
}
