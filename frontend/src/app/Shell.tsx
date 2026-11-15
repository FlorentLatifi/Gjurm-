import { Suspense, useEffect, useId, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { SiteNotice, StatusPill } from "@/features/system";
import { formatToday } from "@/shared/lib/format";
import { LoadingBlock } from "@/ui/States";

import { RouteError } from "./RouteError";
import { LanguageToggle } from "./LanguageToggle";
import { RouteFocus } from "./RouteFocus";
import { SiteSearch } from "./SiteSearch";
import { ThemeToggle } from "./ThemeToggle";
import "./shell.css";
import { labels, t } from "@/shared/i18n";

const NAV_LABEL = labels({
  stories: "Home",
  myNews: "For you",
  blindspot: "Blindspot",
  topics: "Topics",
  dashboard: "Dashboard",
  trends: "Trends",
  entities: "People",
  sources: "Sources",
  articles: "Articles",
  about: "Methodology",
  status: "Status",
});
type NavItem = { to: string; label: keyof typeof NAV_LABEL; end?: boolean };
/** The section line under the nameplate: what a reader comes for. */
const NAV: NavItem[] = [
  { to: "/", label: "stories", end: true },
  { to: "/blindspot", label: "blindspot" },
  { to: "/my-news", label: "myNews" },
  { to: "/topics", label: "topics" },
  { to: "/sources", label: "sources" },
  { to: "/about", label: "about" },
];
/** The analysis pages, behind the menu button. */
const MORE: NavItem[] = [
  { to: "/dashboard", label: "dashboard" },
  { to: "/trends", label: "trends" },
  { to: "/entities", label: "entities" },
  { to: "/articles", label: "articles" },
  { to: "/status", label: "status" },
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

/** Every section, the analysis pages included: a panel under the menu button. */
function SectionsMenu() {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const [at, setAt] = useState(location.key);
  if (location.key !== at) {
    setAt(location.key);
    setOpen(false);
  }
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <>
      <button ref={button} type="button" className="menu-button" aria-expanded={open} aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}>
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden>
          <path d="M3 5.5h14M3 10h14M3 14.5h9" />
        </svg>
        <span className="visually-hidden">{t("All sections")}</span>
      </button>
      <nav id={panelId} className="sections-menu" aria-label={t("All sections")} hidden={!open}>
        <ul>
          {[...NAV, ...MORE].map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={item.end}>{NAV_LABEL[item.label]}</NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}

export function Shell() {
  return (
    <>
      <RouteFocus />
      <a href="#main" className="skip-link">
        {t("Skip to content")}
      </a>
      <header className="masthead">
        <div className="masthead__inner">
          <p className="masthead__date">
            <time>{formatToday()}</time>
            <StatusPill />
          </p>
          {/* the nameplate: the ë's two dots are drawn as squares of ink (shell.css) */}
          <Link to="/" className="plate" aria-label={t("GJURMË home")}>
            <span aria-hidden="true">Gjurm<span className="plate__e">e</span></span>
          </Link>
          <div className="masthead__tools">
            <SiteSearch />
            <ThemeToggle />
            <LanguageToggle />
          </div>
          <p className="masthead__motto">{t("One story, every side")}</p>
        </div>
        <div className="sections">
          <SectionsMenu />
          <nav className="nav" aria-label={t("Main")}>
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}>
                {NAV_LABEL[item.label]}
              </NavLink>
            ))}
          </nav>
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
