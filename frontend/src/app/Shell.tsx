import { Suspense, useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { AnalysisBanner, DemoBanner, StatusPill } from "@/features/system";
import { LoadingBlock } from "@/ui/States";

import { RouteError } from "./RouteError";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { to: "/", label: "Stories", end: true },
  { to: "/blindspot", label: "Blindspot" },
  { to: "/my-news", label: "My bias" },
  { to: "/dashboard", label: "Dashboard" },
  { to: "/trends", label: "Trends" },
  { to: "/topics", label: "Topics" },
  { to: "/entities", label: "People" },
  { to: "/sources", label: "Sources" },
  { to: "/articles", label: "Articles" },
  { to: "/about", label: "Methodology" },
];

export function Shell() {
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
        <AnalysisBanner />
        {/* One page failing (or its code not loading) never takes the header and navigation down. */}
        <RouteError key={location.pathname}>
          <Suspense fallback={<LoadingBlock height={320} label="Loading page" />}>
            <Outlet />
          </Suspense>
        </RouteError>
      </main>
      <footer className="site-footer">
        <div className="site-footer__inner">
          <p>
            Headlines belong to their publishers — every item links to the original article.
            Topics, entities, tone and summaries are AI-generated and can be wrong; outlet ratings
            are editorial.{" "}
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
