import "@/design/app.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { installPreloadRecovery } from "./chunkReload";
import { installPreferences } from "./preferences";
import { queryClient } from "./queryClient";
import { routes } from "./router";

const root = document.getElementById("root");
if (root) {
  installPreloadRecovery();
  installPreferences();
  const router = createBrowserRouter(routes);
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
}
