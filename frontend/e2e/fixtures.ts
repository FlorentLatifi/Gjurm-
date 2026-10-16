import { test as base } from "@playwright/test";

export { expect } from "@playwright/test";

/**
 * The suite reads the interface in English; Albanian, the default, has its own tests (they use
 * `albanian`). A language the test itself chose is never overwritten.
 */
export const test = base.extend<{ albanian: boolean }>({
  albanian: [false, { option: true }],
  page: async ({ page, albanian }, provide) => {
    if (!albanian) {
      await page.addInitScript(
        "try { var k = 'gjurme-prefs'; var v = JSON.parse(localStorage.getItem(k) || 'null') || { state: {}, version: 1 };" +
          " if (!v.state.lang) { v.state.lang = 'en'; localStorage.setItem(k, JSON.stringify(v)); } } catch (e) {}",
      );
    }
    await provide(page);
  },
});
