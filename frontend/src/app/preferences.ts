import { PREFERENCES_KEY, type Theme, usePreferences } from "@/stores/preferences";
import { READING_KEY, useReadingStore } from "@/stores/reading";
import { syncAcrossTabs } from "@/stores/storage";

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

/**
 * Keeps the document in step with the stored preferences: the theme attribute follows the store
 * (public/theme.js already applied it before first paint), and another tab's changes to the
 * theme, lens or reading history show up here too.
 */
export function installPreferences() {
  applyTheme(usePreferences.getState().theme);
  usePreferences.subscribe((s, prev) => {
    if (s.theme !== prev.theme) applyTheme(s.theme);
  });
  syncAcrossTabs(PREFERENCES_KEY, () => usePreferences.persist.rehydrate());
  syncAcrossTabs(READING_KEY, () => useReadingStore.persist.rehydrate());
}
