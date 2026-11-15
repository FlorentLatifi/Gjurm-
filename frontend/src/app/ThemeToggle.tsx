import type { ReactNode } from "react";

import { type Theme, usePreferences } from "@/stores/preferences";
import { labels, t } from "@/shared/i18n";

const LABEL = labels({ light: "Light", dark: "Dark", system: "Auto" });
const ORDER: Theme[] = ["light", "dark", "system"];
// drawn, not emoji: a sun, a crescent, and a half-inked disc for "follow the device"
const ICON: Record<Theme, ReactNode> = {
  light: (
    <>
      <circle cx="10" cy="10" r="3.4" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
    </>
  ),
  dark: <path d="M16 11.6A6.6 6.6 0 0 1 8.4 4 6.6 6.6 0 1 0 16 11.6Z" />,
  system: (
    <>
      <circle cx="10" cy="10" r="6.5" />
      <path d="M10 3.5v13a6.5 6.5 0 0 0 0-13Z" fill="currentColor" stroke="none" />
    </>
  ),
};

/** The colour theme: light, dark, or the device's own. The chosen one is pressed. */
export function ThemeToggle() {
  const theme = usePreferences((s) => s.theme);
  const setTheme = usePreferences((s) => s.setTheme);
  return (
    <div className="theme-choice" role="group" aria-label={t("Colour theme")}>
      {ORDER.map((option) => (
        <button key={option} type="button" aria-pressed={theme === option} title={LABEL[option]} onClick={() => setTheme(option)}>
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            {ICON[option]}
          </svg>
          <span className="visually-hidden">{LABEL[option]}</span>
        </button>
      ))}
    </div>
  );
}
