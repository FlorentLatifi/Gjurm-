import { type Theme, usePreferences } from "@/stores/preferences";

const NEXT: Record<Theme, Theme> = { system: "dark", dark: "light", light: "system" };
const LABEL: Record<Theme, string> = { system: "Auto", dark: "Dark", light: "Light" };

function Icon({ theme }: { theme: Theme }) {
  const common = { viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.5, "aria-hidden": true } as const;
  if (theme === "dark") {
    return (
      <svg {...common}>
        <path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7Z" strokeLinejoin="round" />
      </svg>
    );
  }
  if (theme === "light") {
    return (
      <svg {...common} strokeLinecap="round">
        <circle cx="8" cy="8" r="3" />
        <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 2a6 6 0 0 1 0 12Z" fill="currentColor" stroke="none" />
    </svg>
  );
}

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
      <Icon theme={theme} /> <span className="site-header__label">{LABEL[theme]}</span>
    </button>
  );
}
