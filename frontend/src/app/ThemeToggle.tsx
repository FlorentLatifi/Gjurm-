import { useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem("gjurme-theme");
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") delete root.dataset.theme;
    else root.dataset.theme = theme;
    try {
      if (theme === "system") localStorage.removeItem("gjurme-theme");
      else localStorage.setItem("gjurme-theme", theme);
    } catch {
      /* storage unavailable: preference lasts for this page view only */
    }
  }, [theme]);
  const next: Theme = theme === "system" ? "dark" : theme === "dark" ? "light" : "system";
  const label = { system: "Auto", dark: "Dark", light: "Light" }[theme];
  return (
    <button
      type="button"
      className="btn btn--ghost btn--sm"
      onClick={() => setTheme(next)}
      aria-label={`Colour theme: ${label}. Switch to ${next}.`}
    >
      <span aria-hidden="true">{theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"}</span> {label}
    </button>
  );
}
