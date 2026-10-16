import "@/design/index.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { installPreloadRecovery } from "./chunkReload";
import { LanguageRoot } from "./LanguageRoot";
import { installPreferences } from "./preferences";
import { queryClient } from "./queryClient";
import { RouteError } from "./RouteError";
import { AppRoutes } from "./router";

const root = document.getElementById("root");
if (root) {
  installPreloadRecovery();
  installPreferences();
  createRoot(root).render(
    <StrictMode>
      {/* last line of defence: pages have their own boundary inside the shell */}
      <RouteError>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <LanguageRoot>
              <AppRoutes />
            </LanguageRoot>
          </BrowserRouter>
        </QueryClientProvider>
      </RouteError>
    </StrictMode>,
  );
}
