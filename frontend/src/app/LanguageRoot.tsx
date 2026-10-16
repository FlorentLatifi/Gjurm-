import { Fragment, type ReactNode } from "react";

import { usePreferences } from "@/stores/preferences";

/**
 * Renders the app anew when the interface language changes: text is looked up while rendering
 * (shared/i18n), so every component must render again, memoised ones included. Data stays in the
 * query cache and the URL is kept.
 */
export function LanguageRoot({ children }: { children: ReactNode }) {
  const lang = usePreferences((s) => s.lang);
  return <Fragment key={lang}>{children}</Fragment>;
}
