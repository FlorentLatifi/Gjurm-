import "@/design/app.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ApiError } from "@/shared/api/client";
import { Shell } from "./Shell";
import { installPreloadRecovery } from "./chunkReload";

// Route-level code splitting: the stories feed loads first; other pages load on demand.
const Stories = lazy(() => import("@/features/stories/pages/Feed"));
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

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (count, error) =>
        count < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
  },
});

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Stories />} />
        <Route path="stories/:id" element={<Story />} />
        <Route path="blindspot" element={<Blindspot />} />
        <Route path="my-news" element={<MyNews />} />
        <Route path="dashboard" element={<Overview />} />
        <Route path="trends" element={<Trends />} />
        <Route path="topics" element={<Topics />} />
        <Route path="topics/:slug" element={<Topic />} />
        <Route path="entities" element={<Entities />} />
        <Route path="entities/:id" element={<Entity />} />
        <Route path="sources" element={<Sources />} />
        <Route path="sources/:slug" element={<SourceProfile />} />
        <Route path="articles" element={<Articles />} />
        <Route path="articles/:id" element={<Article />} />
        <Route path="about" element={<About />} />
        <Route path="status" element={<Status />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

const root = document.getElementById("root");
if (root) {
  installPreloadRecovery();
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
