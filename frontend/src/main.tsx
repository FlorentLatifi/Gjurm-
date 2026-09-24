import "./styles/app.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ApiError } from "./api/client";
import { Layout } from "./components/Layout";
import { LoadingBlock } from "./components/States";

// Route-level code splitting: the overview loads first; other pages load on demand.
const Overview = lazy(() => import("./pages/Overview"));
const Trends = lazy(() => import("./pages/Trends"));
const Sources = lazy(() => import("./pages/Sources"));
const Topics = lazy(() => import("./pages/Topics").then((m) => ({ default: m.TopicsPage })));
const Topic = lazy(() => import("./pages/Topics").then((m) => ({ default: m.TopicPage })));
const Entities = lazy(() => import("./pages/Entities").then((m) => ({ default: m.EntitiesPage })));
const Entity = lazy(() => import("./pages/Entities").then((m) => ({ default: m.EntityPage })));
const Articles = lazy(() => import("./pages/Articles").then((m) => ({ default: m.ArticlesPage })));
const Article = lazy(() => import("./pages/Articles").then((m) => ({ default: m.ArticlePage })));
const About = lazy(() => import("./pages/Info").then((m) => ({ default: m.AboutPage })));
const Status = lazy(() => import("./pages/Info").then((m) => ({ default: m.StatusPage })));
const NotFound = lazy(() => import("./pages/Info").then((m) => ({ default: m.NotFoundPage })));

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
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="trends" element={<Trends />} />
        <Route path="topics" element={<Topics />} />
        <Route path="topics/:slug" element={<Topic />} />
        <Route path="entities" element={<Entities />} />
        <Route path="entities/:id" element={<Entity />} />
        <Route path="sources" element={<Sources />} />
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
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Suspense fallback={<main style={{ padding: 24 }}><LoadingBlock /></main>}>
            <AppRoutes />
          </Suspense>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
