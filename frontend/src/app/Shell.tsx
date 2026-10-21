import { Suspense, useEffect, useId, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { entitySpikesQuery } from "@/features/analytics";
import { SiteNotice, StatusPill, taxonomyQuery } from "@/features/system";
import { formatToday } from "@/shared/lib/format";
import { countryLabel, REGION_ORDER } from "@/shared/model/ratings";
import { useApiQuery } from "@/shared/query/apiQuery";
import { LoadingBlock } from "@/ui/States";

import { RouteError } from "./RouteError";
import { LanguageToggle } from "./LanguageToggle";
import { RouteFocus } from "./RouteFocus";
import { SiteSearch } from "./SiteSearch";
import { ThemeToggle } from "./ThemeToggle";
import "./shell.css";
import { labels, localName, t } from "@/shared/i18n";

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
/** The masthead's own links, as on Ground News: Home, For you, Blindspot (and topics). */
const NAV: NavItem[] = [
  { to: "/", label: "stories", end: true },
  { to: "/my-news", label: "myNews" },
  { to: "/blindspot", label: "blindspot" },
  { to: "/topics", label: "topics" },
];
/** Everything else, behind the menu button. */
const MORE: NavItem[] = [
  { to: "/dashboard", label: "dashboard" },
  { to: "/trends", label: "trends" },
  { to: "/entities", label: "entities" },
  { to: "/sources", label: "sources" },
  { to: "/articles", label: "articles" },
  { to: "/about", label: "about" },
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

/** "Edition": the story feed of one country's outlets, as Ground News' edition picker. */
function EditionPicker() {
  const id = useId();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const current = pathname === "/" ? (params.get("country") ?? "") : "";
  return (
    <span className="strip-select">
      <label htmlFor={id}>{t("Edition")}</label>
      <select id={id} value={current} onChange={(e) => navigate(e.target.value ? `/?country=${e.target.value}` : "/")}>
        <option value="">{t("All outlets")}</option>
        {REGION_ORDER.filter((c) => c !== "REG").map((c) => (
          <option key={c} value={c}>{countryLabel(c)}</option>
        ))}
      </select>
    </span>
  );
}

/** The sections not in the masthead: a panel under the menu button. */
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

/**
 * The trending row under the masthead: names suddenly in the news, then the topics. Ground News
 * puts a "+" on each to follow it; here the "+" opens it.
 */
function TrendingBar() {
  const spikes = useApiQuery(entitySpikesQuery(6));
  const topics = useApiQuery(taxonomyQuery());
  // decoration around every page: whatever the API answers, it never breaks the page
  const names = Array.isArray(spikes.data?.items) ? spikes.data.items : [];
  const taxonomy = Array.isArray(topics.data) ? topics.data : [];
  const chips = [
    ...names.map((e) => ({ key: `e${e.id}`, to: `/entities/${e.id}`, label: e.name })),
    ...taxonomy.map((tp) => ({ key: `t${tp.slug}`, to: `/topics/${tp.slug}`, label: localName(tp.name_en, tp.name_sq) })),
  ];
  if (!chips.length) return null;
  return (
    <nav className="trending" aria-label={t("Trending")}>
      <div className="trending__inner">
        <svg className="trending__icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.8}
          strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M2.5 14.5 8 9l3.5 3.5 6-6M13 6.5h4.5V11" />
        </svg>
        <ul>
          {chips.map((c) => (
            <li key={c.key}>
              <Link className="trend-chip" to={c.to}>{c.label} <span aria-hidden="true">+</span></Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}

export function Shell() {
  return (
    <>
      <RouteFocus />
      <a href="#main" className="skip-link">
        {t("Skip to content")}
      </a>
      <div className="promo">
        <p>{t("See every side of every story")}</p>
        <Link className="promo__button" to="/about#stories">{t("How it works")}</Link>
      </div>
      <div className="strip">
        <div className="strip__inner">
          <div className="strip__group">
            <ThemeToggle />
            <LanguageToggle />
          </div>
          <div className="strip__group">
            <StatusPill />
            <span className="strip__date">{formatToday()}</span>
            <EditionPicker />
          </div>
        </div>
      </div>
      <header className="site-header">
        <div className="site-header__inner">
          <SectionsMenu />
          <Link to="/" className="brand" aria-label={t("GJURMË home")}>
            <span className="brand__name">GJURMË</span>
            <span className="brand__sub">{t("News")}</span>
          </Link>
          <nav className="nav" aria-label={t("Main")}>
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}>
                {NAV_LABEL[item.label]}
              </NavLink>
            ))}
          </nav>
          <div className="header-actions">
            <SiteSearch />
            <Link className="btn btn--solid header-actions__wide" to="/sources">{t("Outlets")}</Link>
            <Link className="btn header-actions__wide" to="/about">{t("Methodology")}</Link>
          </div>
        </div>
      </header>
      <TrendingBar />
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
