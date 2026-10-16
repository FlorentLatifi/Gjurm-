import "@testing-library/jest-dom/vitest";

import { setLang } from "@/shared/i18n";

// Recharts' ResponsiveContainer needs ResizeObserver; jsdom does not provide it.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia;

// The suites check English text; src/test/i18n.test.ts covers the Albanian interface.
setLang("en");
