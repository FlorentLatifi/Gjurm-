import { Suspense } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { SiteNotice, StatusPill } from "@/features/system";
import { LoadingBlock } from "@/ui/States";

import { RouteError } from "./RouteError";
import { LanguageToggle } from "./LanguageToggle";
import { RouteFocus } from "./RouteFocus";
import { SiteSearch } from "./SiteSearch";
import { ThemeToggle } from "./ThemeToggle";
import "./shell.css";
import { labels, t } from "@/shared/i18n";

const NAV_LABEL = labels({
  stories: "Stories",
  blindspot: "Blindspot",
  myNews: "My bias",
  dashboard: "Dashboard",
  trends: "Trends",
  topics: "Topics",
  entities: "People",
  sources: "Sources",
  articles: "Articles",
  about: "Methodology",
});
const NAV: { to: string; label: keyof typeof NAV_LABEL; end?: boolean }[] = [
  { to: "/", label: "stories", end: true },
  { to: "/blindspot", label: "blindspot" },
  { to: "/my-news", label: "myNews" },
  { to: "/dashboard", label: "dashboard" },
  { to: "/trends", label: "trends" },
  { to: "/topics", label: "topics" },
  { to: "/entities", label: "entities" },
  { to: "/sources", label: "sources" },
  { to: "/articles", label: "articles" },
  { to: "/about", label: "about" },
];

/** The current page, isolated: its error or its loading state never replaces the shell. */
function RoutePage() {
  const { pathname } = useLocation();
  return (
    <RouteError key={pathname}>
      <Suspense fallback={<LoadingBlock height={320} label={t("Loading page")} />}>
        <Outlet />
      </Suspense>
    </RouteError>
  );
}

export function Shell() {
  return (
    <>
      <RouteFocus />
      <a href="#main" className="skip-link">
        {t("Skip to content")}
      </a>
      <header className="site-header">
        <div className="site-header__inner">
          <Link to="/" className="brand" aria-label={t("GJURMË home")}>
            <img src="/favicon.svg" width={28} height={28} alt="" />
            <span>
              <span className="brand__name">GJURMË</span>
              <small>{t("Every side of the Albanian-language news")}</small>
            </span>
          </Link>
          <nav className="nav" aria-label={t("Main")}>
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}>
                {NAV_LABEL[item.label]}
              </NavLink>
            ))}
          </nav>
          <div className="header-actions">
            <StatusPill />
            <SiteSearch />
            <ThemeToggle />
            <LanguageToggle />
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        <SiteNotice />
        <RoutePage />
      </main>
      <footer className="site-footer">
        <div className="site-footer__inner">
          <p>
            {t("Headlines belong to their publishers — every item links to the original article. Topics, entities, tone and summaries are AI-generated and can be wrong; outlet ratings are editorial.")}{" "}
            <Link to="/about">{t("How it works")}</Link>
          </p>
          <p>
            <a href="/api/docs">{t("Public API")}</a> · <Link to="/status">{t("Status")}</Link> ·{" "}
            <Link to="/about#contact">{t("Corrections & removal")}</Link>
          </p>
        </div>
      </footer>
    </>
  );
}
