import { type Theme, usePreferences } from "@/stores/preferences";

const NEXT: Record<Theme, Theme> = { system: "dark", dark: "light", light: "system" };
const LABEL: Record<Theme, string> = { system: "Auto", dark: "Dark", light: "Light" };
const ICON: Record<Theme, string> = { system: "◐", dark: "☾", light: "☀" };

export function ThemeToggle() {
  const theme = usePreferences((s) => s.theme);
  const setTheme = usePreferences((s) => s.setTheme);
  const next = NEXT[theme];
  return (
    <button
      type="button"
      className="btn btn--ghost btn--sm"
      onClick={() => setTheme(next)}
      aria-label={`Colour theme: ${LABEL[theme]}. Switch to ${next}.`}
    >
      <span aria-hidden="true">{ICON[theme]}</span> {LABEL[theme]}
    </button>
  );
}
