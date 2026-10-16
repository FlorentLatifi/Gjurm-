import { setLang } from "@/shared/i18n";
import { PREFERENCES_KEY, type Theme, usePreferences } from "@/stores/preferences";
import { READING_KEY, useReadingStore } from "@/stores/reading";
import { syncAcrossTabs } from "@/stores/storage";

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

/**
 * Keeps the document in step with the stored preferences: the theme attribute and the interface
 * language follow the store (public/theme.js already applied both before first paint), and another
 * tab's changes to the theme, lens, language or reading history show up here too.
 * Subscribed before React renders, so the language is set before the app renders in it.
 */
export function installPreferences() {
  applyTheme(usePreferences.getState().theme);
  setLang(usePreferences.getState().lang);
  usePreferences.subscribe((s, prev) => {
    if (s.theme !== prev.theme) applyTheme(s.theme);
    if (s.lang !== prev.lang) setLang(s.lang);
  });
  syncAcrossTabs(PREFERENCES_KEY, () => usePreferences.persist.rehydrate());
  syncAcrossTabs(READING_KEY, () => useReadingStore.persist.rehydrate());
}
