import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { lazy, type ReactNode, useLayoutEffect } from "react";
import { matchRoutes, Route, Routes, useLocation } from "react-router-dom";

import {
  entitiesQueries,
  entityQueries,
  overviewQueries,
  topicQueries,
  topicsQueries,
  trendsQueries,
} from "@/features/analytics/queries";
import { articleQueries, articlesQueries } from "@/features/articles/queries";
import { myNewsQueries } from "@/features/reading/queries";
import { sourceProfileQueries, sourcesQueries } from "@/features/sources/queries";
import { blindspotQueries, feedQueries, storyQueries } from "@/features/stories/queries";
import { statusQuery, taxonomyQuery } from "@/features/system";
import { isPositiveId } from "@/shared/lib/ids";

import { useScrollMemory } from "./scrollMemory";
import { Shell } from "./Shell";

// Route-level code splitting: each page is its own chunk, loaded when first rendered.
const Feed = lazy(() => import("@/features/stories/pages/Feed"));
const Story = lazy(() => import("@/features/stories/pages/Story").then((m) => ({ default: m.StoryPage })));
const Blindspot = lazy(() => import("@/features/stories/pages/Blindspot"));
const MyNews = lazy(() => import("@/features/reading/pages/MyNews"));
const SourceProfile = lazy(() =>
  import("@/features/sources/pages/SourceProfile").then((m) => ({ default: m.SourceProfilePage })),
);
const Overview = lazy(() => import("@/features/analytics/pages/Overview"));
const Trends = lazy(() => import("@/features/analytics/pages/Trends"));
const Sources = lazy(() => import("@/features/sources/pages/Sources"));
const Topics = lazy(() => import("@/features/analytics/pages/Topics").then((m) => ({ default: m.TopicsPage })));
const Topic = lazy(() => import("@/features/analytics/pages/Topics").then((m) => ({ default: m.TopicPage })));
const Entities = lazy(() => import("@/features/analytics/pages/Entities").then((m) => ({ default: m.EntitiesPage })));
const Entity = lazy(() => import("@/features/analytics/pages/Entities").then((m) => ({ default: m.EntityPage })));
const Articles = lazy(() => import("@/features/articles/pages/Articles").then((m) => ({ default: m.ArticlesPage })));
const Article = lazy(() => import("@/features/articles/pages/Articles").then((m) => ({ default: m.ArticlePage })));
const About = lazy(() => import("@/features/system/pages/Info").then((m) => ({ default: m.AboutPage })));
const Status = lazy(() => import("@/features/system/pages/Info").then((m) => ({ default: m.StatusPage })));
const NotFound = lazy(() => import("@/features/system/pages/Info").then((m) => ({ default: m.NotFoundPage })));

type Queries = Record<string, unknown>;
type Params = Record<string, string | undefined>;

interface AppRoute {
  path: string;
  element: ReactNode;
  /** The page's queries, from its URL: started when the route is entered, alongside its code. */
  prefetch?: (search: URLSearchParams, params: Params) => Queries | null;
}

const byId = (build: (id: number) => Queries) => (_: URLSearchParams, p: Params) => {
  const id = Number(p.id);
  return isPositiveId(id) ? build(id) : null;
};

export const appRoutes: AppRoute[] = [
  { path: "/", element: <Feed />, prefetch: (s) => feedQueries(s) },
  { path: "/stories/:id", element: <Story />, prefetch: byId(storyQueries) },
  { path: "/blindspot", element: <Blindspot />, prefetch: (s) => blindspotQueries(s) },
  { path: "/my-news", element: <MyNews />, prefetch: () => myNewsQueries() },
  { path: "/dashboard", element: <Overview />, prefetch: (s) => overviewQueries(s) },
  { path: "/trends", element: <Trends />, prefetch: (s) => trendsQueries(s) },
  { path: "/topics", element: <Topics />, prefetch: (s) => topicsQueries(s) },
  { path: "/topics/:slug", element: <Topic />, prefetch: (s, p) => topicQueries(p.slug ?? "", s) },
  { path: "/entities", element: <Entities />, prefetch: (s) => entitiesQueries(s) },
  { path: "/entities/:id", element: <Entity />, prefetch: (s, p) => byId((id) => entityQueries(id, s))(s, p) },
  { path: "/sources", element: <Sources />, prefetch: (s) => sourcesQueries(s) },
  { path: "/sources/:slug", element: <SourceProfile />, prefetch: (s, p) => sourceProfileQueries(p.slug ?? "", s) },
  { path: "/articles", element: <Articles />, prefetch: (s) => articlesQueries(s) },
  { path: "/articles/:id", element: <Article />, prefetch: byId(articleQueries) },
  { path: "/about", element: <About />, prefetch: () => ({ taxonomy: taxonomyQuery(), status: statusQuery() }) },
  { path: "/status", element: <Status />, prefetch: () => ({ status: statusQuery() }) },
  { path: "*", element: <NotFound /> },
];

const matchable = appRoutes.map((r, i) => ({ path: r.path, id: String(i) }));

/**
 * Starts the requests of the page at `location` without waiting for them (prefetchQuery never
 * throws). The page reads the same cache entries and shows its own loading, error and empty
 * states; until then its code chunk is downloading in parallel.
 */
export function prefetchRoute(client: QueryClient, location: { pathname: string; search: string }): boolean {
  const match = matchRoutes(matchable, location.pathname)?.[0];
  const route = match ? appRoutes[Number(match.route.id)] : undefined;
  const queries = route?.prefetch?.(new URLSearchParams(location.search), match!.params);
  if (!queries) return false;
  type Prefetchable = Parameters<QueryClient["prefetchQuery"]>[0];
  for (const q of Object.values(queries)) void client.prefetchQuery(q as Prefetchable);
  return true;
}

/** Router-driven side effects that the shell should not know about. */
function RouteEffects() {
  const location = useLocation();
  const client = useQueryClient();
  useScrollMemory();
  useLayoutEffect(() => {
    prefetchRoute(client, location);
  }, [client, location]);
  return null;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route
        element={
          <>
            <RouteEffects />
            <Shell />
          </>
        }
      >
        {appRoutes.map((r) => (
          <Route key={r.path} path={r.path} element={r.element} />
        ))}
      </Route>
    </Routes>
  );
}
