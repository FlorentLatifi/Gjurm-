/**
 * Microsoft Clarity: heatmaps and recordings of how pages are used, without cookies (ADR-036).
 * Only in the production deploy on Vercel, where the build sets VITE_CLARITY_ID (vite.config.ts);
 * dev, CI, the e2e build, preview deploys and the Docker image never load it.
 *
 * - No cookies of its own here: before the tag loads, Clarity is told consent to storage is denied
 *   (Consent API v2), so it sets no cookie on this site and counts each page view on its own. Its
 *   servers can still keep cookies on clarity.ms itself where a browser allows third-party cookies
 *   (the tag's sync pixel, its credentialed uploads); the tag is fetched without credentials so its
 *   own answer cannot. The Privacy page says so.
 * - Not loaded for a reader whose browser asks not to be tracked (Global Privacy Control or Do Not
 *   Track).
 * - Off the critical path: the tag is added a few seconds after the page's load event, when the
 *   main thread is idle. The load event comes before the page's data (fetches do not hold it), so
 *   without the wait its 75 KB script would compete with the first stories.
 * - No inline script: the tag is an external file the CSP allows (script-src www.clarity.ms and
 *   scripts.clarity.ms, connect-src *.clarity.ms), so the CSP still forbids inline scripts.
 *
 * Text typed into inputs (the search) is masked by Clarity in every mode; the page's address,
 * with a search's terms and filters, is recorded. The Privacy page says so.
 */
type Clarity = ((...args: unknown[]) => void) & { q?: unknown[][] };
type ClarityWindow = Window & { clarity?: Clarity };
type PrivacySignals = Navigator & { globalPrivacyControl?: boolean };

const TAG = "https://www.clarity.ms/tag/";
/** After the load event: time for the first page's data and code to arrive and render. */
export const CLARITY_DELAY_MS = 4000;

/** Whether the reader's browser asks sites not to track it. */
export function asksNotToTrack(nav: PrivacySignals = navigator): boolean {
  return nav.globalPrivacyControl === true || nav.doNotTrack === "1";
}

/** Queues the cookieless consent and schedules the tag; false when it is not loaded at all. */
export function installClarity(project: string | undefined, win: ClarityWindow = window): boolean {
  if (!project || !/^[a-z0-9]{6,20}$/i.test(project) || win.clarity || asksNotToTrack(win.navigator)) return false;
  // the queue Clarity's own snippet defines: calls made before the tag arrives are replayed by it
  const clarity: Clarity = (...args) => {
    (clarity.q ??= []).push(args);
  };
  win.clarity = clarity;
  clarity("consentv2", { ad_Storage: "denied", analytics_Storage: "denied" });

  const load = () => {
    const tag = win.document.createElement("script");
    tag.async = true;
    // fetched without credentials: the tag's own answer sets a year-long cookie on clarity.ms
    // (CLID), which the browser ignores for an anonymous request (the tag allows any origin)
    tag.crossOrigin = "anonymous";
    tag.src = TAG + project;
    win.document.head.appendChild(tag);
  };
  const whenIdle = () =>
    win.setTimeout(() => {
      if (typeof win.requestIdleCallback === "function") win.requestIdleCallback(load, { timeout: 5000 });
      else load();
    }, CLARITY_DELAY_MS);
  if (win.document.readyState === "complete") whenIdle();
  else win.addEventListener("load", whenIdle, { once: true });
  return true;
}
