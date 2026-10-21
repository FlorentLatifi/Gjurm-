import { type Theme, usePreferences } from "@/stores/preferences";
import { labels, t } from "@/shared/i18n";

const LABEL = labels({ light: "Light", dark: "Dark", system: "Auto" });
const ORDER: Theme[] = ["light", "dark", "system"];

/** "Theme: Light Dark Auto", as in Ground News' top strip: the chosen one is pressed. */
export function ThemeToggle() {
  const theme = usePreferences((s) => s.theme);
  const setTheme = usePreferences((s) => s.setTheme);
  return (
    <div className="strip-choice" role="group" aria-label={t("Colour theme")}>
      <span className="strip-choice__label" aria-hidden="true">{t("Theme:")}</span>
      {ORDER.map((option) => (
        <button key={option} type="button" aria-pressed={theme === option} onClick={() => setTheme(option)}>
          {LABEL[option]}
        </button>
      ))}
    </div>
  );
}
