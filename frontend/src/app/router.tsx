import type { QueryClient } from "@tanstack/react-query";
import { lazy } from "react";
import { type LoaderFunctionArgs, type RouteObject, ScrollRestoration } from "react-router-dom";

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

import { AppError } from "./AppError";
import { queryClient } from "./queryClient";
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

type Prefetchable = Parameters<QueryClient["prefetchQuery"]>[0];

/**
 * Loaders never block navigation: they start the page's requests (in parallel with its code
 * chunk) and return at once. The page reads the same cache entries and shows its own loading,
 * error and empty states.
 */
function prefetch(queries: Record<string, unknown>): null {
  for (const q of Object.values(queries)) void queryClient.prefetchQuery(q as Prefetchable);
  return null;
}

const search = ({ request }: LoaderFunctionArgs) => new URL(request.url).searchParams;
const id = ({ params }: LoaderFunctionArgs) => Number(params.id);

/** Scroll positions are kept per path: filter and page changes do not jump to the top, Back restores. */
function Root() {
  return (
    <>
      <ScrollRestoration getKey={(location) => location.pathname} />
      <Shell />
    </>
  );
}

export const routes: RouteObject[] = [
  {
    element: <Root />,
    errorElement: <AppError />,
    hydrateFallbackElement: <></>,
    children: [
      { index: true, element: <Feed />, loader: (a) => prefetch(feedQueries(search(a))) },
      { path: "stories/:id", element: <Story />, loader: (a) => (isPositiveId(id(a)) ? prefetch(storyQueries(id(a))) : null) },
      { path: "blindspot", element: <Blindspot />, loader: (a) => prefetch(blindspotQueries(search(a))) },
      { path: "my-news", element: <MyNews />, loader: () => prefetch(myNewsQueries()) },
      { path: "dashboard", element: <Overview />, loader: (a) => prefetch(overviewQueries(search(a))) },
      { path: "trends", element: <Trends />, loader: (a) => prefetch(trendsQueries(search(a))) },
      { path: "topics", element: <Topics />, loader: (a) => prefetch(topicsQueries(search(a))) },
      { path: "topics/:slug", element: <Topic />, loader: (a) => prefetch(topicQueries(a.params.slug ?? "", search(a))) },
      { path: "entities", element: <Entities />, loader: (a) => prefetch(entitiesQueries(search(a))) },
      {
        path: "entities/:id",
        element: <Entity />,
        loader: (a) => (isPositiveId(id(a)) ? prefetch(entityQueries(id(a), search(a))) : null),
      },
      { path: "sources", element: <Sources />, loader: (a) => prefetch(sourcesQueries(search(a))) },
      {
        path: "sources/:slug",
        element: <SourceProfile />,
        loader: (a) => prefetch(sourceProfileQueries(a.params.slug ?? "", search(a))),
      },
      { path: "articles", element: <Articles />, loader: (a) => prefetch(articlesQueries(search(a))) },
      { path: "articles/:id", element: <Article />, loader: (a) => (isPositiveId(id(a)) ? prefetch(articleQueries(id(a))) : null) },
      { path: "about", element: <About />, loader: () => prefetch({ taxonomy: taxonomyQuery(), status: statusQuery() }) },
      { path: "status", element: <Status />, loader: () => prefetch({ status: statusQuery() }) },
      { path: "*", element: <NotFound /> },
    ],
  },
];


