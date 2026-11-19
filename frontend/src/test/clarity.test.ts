import { asksNotToTrack, CLARITY_DELAY_MS, installClarity } from "@/app/clarity";

type Win = Parameters<typeof installClarity>[1];

/** A window whose load event and idle callback the test fires by hand. */
function fakeWindow({ ready = "loading", gpc = false, dnt = null as string | null } = {}) {
  const doc = document.implementation.createHTMLDocument("t");
  Object.defineProperty(doc, "readyState", { value: ready });
  const listeners: Record<string, () => void> = {};
  const idle: Array<() => void> = [];
  const timers: Array<[() => void, number]> = [];
  const win = {
    document: doc,
    navigator: { globalPrivacyControl: gpc, doNotTrack: dnt },
    addEventListener: (type: string, fn: () => void) => (listeners[type] = fn),
    requestIdleCallback: (fn: () => void) => idle.push(fn),
    setTimeout: (fn: () => void, ms: number) => timers.push([fn, ms]),
  } as unknown as Win & { clarity?: { q?: unknown[][] } };
  return {
    win,
    doc,
    fire: (type: string) => listeners[type]?.(),
    runTimers: () => timers.splice(0).map(([fn, ms]) => (fn(), ms)),
    runIdle: () => idle.splice(0).forEach((fn) => fn()),
  };
}

const tags = (doc: Document) => [...doc.head.querySelectorAll("script")].map((s) => s.src);

describe("Microsoft Clarity (ADR-036)", () => {
  it("queues the cookieless consent first, and adds the tag only after load, a wait and idle time", () => {
    const { win, doc, fire, runTimers, runIdle } = fakeWindow();
    expect(installClarity("zga1xwudy1", win)).toBe(true);
    expect(win.clarity?.q).toEqual([["consentv2", { ad_Storage: "denied", analytics_Storage: "denied" }]]);
    expect(tags(doc)).toEqual([]);
    fire("load");
    expect(tags(doc)).toEqual([]);
    expect(runTimers()).toEqual([CLARITY_DELAY_MS]);
    expect(tags(doc)).toEqual([]);
    runIdle();
    expect(tags(doc)).toEqual(["https://www.clarity.ms/tag/zga1xwudy1"]);
    expect(doc.head.querySelector("script")?.async).toBe(true);
    // without credentials, so the tag's answer cannot set a cookie on clarity.ms
    expect(doc.head.querySelector("script")?.crossOrigin).toBe("anonymous");
  });

  it("does not wait for the load event when the page has already loaded", () => {
    const { win, doc, runTimers, runIdle } = fakeWindow({ ready: "complete" });
    installClarity("zga1xwudy1", win);
    runTimers();
    runIdle();
    expect(tags(doc)).toHaveLength(1);
  });

  it("is not loaded without a valid project, twice, or for a reader who asks not to be tracked", () => {
    expect(installClarity(undefined, fakeWindow().win)).toBe(false);
    expect(installClarity("", fakeWindow().win)).toBe(false);
    expect(installClarity("x/../evil", fakeWindow().win)).toBe(false);
    const { win } = fakeWindow();
    installClarity("zga1xwudy1", win);
    expect(installClarity("zga1xwudy1", win)).toBe(false);
    expect(installClarity("zga1xwudy1", fakeWindow({ gpc: true }).win)).toBe(false);
    expect(installClarity("zga1xwudy1", fakeWindow({ dnt: "1" }).win)).toBe(false);
  });

  it("reads Global Privacy Control and Do Not Track", () => {
    const nav = (signals: { globalPrivacyControl?: boolean; doNotTrack?: string | null }) => signals as unknown as Navigator;
    expect(asksNotToTrack(nav({ globalPrivacyControl: true }))).toBe(true);
    expect(asksNotToTrack(nav({ doNotTrack: "1" }))).toBe(true);
    expect(asksNotToTrack(nav({ doNotTrack: "0" }))).toBe(false);
    expect(asksNotToTrack(nav({ doNotTrack: null }))).toBe(false);
  });
});
