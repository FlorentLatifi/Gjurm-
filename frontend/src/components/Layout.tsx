import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { useStatus } from "../api/hooks";
import { formatRelative } from "../lib/format";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/trends", label: "Trends" },
  { to: "/topics", label: "Topics" },
  { to: "/entities", label: "People & orgs" },
  { to: "/sources", label: "Sources" },
  { to: "/articles", label: "Articles" },
  { to: "/about", label: "Methodology" },
];

type Theme = "light" | "dark" | "system";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem("gjurme-theme");
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

function ThemeToggle() {
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

function StatusPill() {
  const { data } = useStatus();
  if (!data) return null;
  const colour =
    data.status === "ok"
      ? "var(--status-good)"
      : data.status === "degraded"
        ? "var(--status-warning)"
        : "var(--status-critical)";
  const text =
    data.status === "stale" ? "Data not updating" : `Updated ${formatRelative(data.last_success_at)}`;
  return (
    <Link to="/status" className="status-pill" title="Pipeline status">
      <span className="dot" style={{ background: colour }} aria-hidden="true" />
      {text}
    </Link>
  );
}

function DemoBanner() {
  const { data } = useStatus();
  if (!data?.demo_data) return null;
  return (
    <div className="banner" role="note">
      <strong>Demo dataset.</strong> This instance shows synthetic articles from fictional outlets
      (“… Demo”) so the product can be explored without live data. Names of people are invented.
    </div>
  );
}

export function Layout() {
  const location = useLocation();
  const firstRender = useRef(true);
  useEffect(() => {
    // On client-side navigation, move focus to the main landmark so screen readers announce the
    // new page. Not on the initial load: keyboard users must start at the skip link / nav.
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    document.getElementById("main")?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [location.pathname]);

  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <header className="site-header">
        <div className="site-header__inner">
          <Link to="/" className="brand" aria-label="GJURMË home">
            <img src="/favicon.svg" width={28} height={28} alt="" />
            <span>
              GJURMË
              <small>Albanian &amp; Balkan news intelligence</small>
            </span>
          </Link>
          <nav className="nav" aria-label="Main">
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}>
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="header-actions">
            <StatusPill />
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        <DemoBanner />
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="site-footer__inner">
          <p>
            Headlines belong to their publishers — every item links to the original article.
            Topics, entities, tone and summaries are AI-generated and can be wrong.{" "}
            <Link to="/about">How it works</Link>
          </p>
          <p>
            <a href="/api/docs">Public API</a> · <Link to="/status">Status</Link> ·{" "}
            <Link to="/about#contact">Corrections &amp; removal</Link>
          </p>
        </div>
      </footer>
    </>
  );
}
