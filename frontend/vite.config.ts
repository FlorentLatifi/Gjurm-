import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

/**
 * Emits robots.txt and, when the deployment URL is known at build time (VITE_PUBLIC_URL), the
 * absolute og:image. Canonical links and og:url are set per page (shared/hooks/useTitle): one
 * built into index.html would declare every route a copy of the home page. The sitemap is built
 * by the API from the data (Caddy routes /sitemap.xml there).
 */
function seoFiles(publicUrl: string | undefined): Plugin {
  const base = (publicUrl || "").replace(/\/$/, "");
  return {
    name: "gjurme-seo-files",
    apply: "build",
    transformIndexHtml() {
      if (!/^https?:\/\//.test(base)) return [];
      return [{ tag: "meta", attrs: { property: "og:image", content: `${base}/og-image.png` }, injectTo: "head" }];
    },
    generateBundle() {
      const robots = ["User-agent: *", "Allow: /", "Disallow: /api/"];
      if (base) robots.push(`Sitemap: ${base}/sitemap.xml`);
      this.emitFile({ type: "asset", fileName: "robots.txt", source: robots.join("\n") + "\n" });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  return {
    plugins: [react(), seoFiles(env.VITE_PUBLIC_URL)],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: {
      port: 5173,
      proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" },
    },
    preview: { port: 4173, proxy: { "/api": "http://127.0.0.1:8000" } },
    build: {
      sourcemap: true,
      manifest: true,
      target: "es2022",
      rollupOptions: {
        output: {
          manualChunks: (id) => {
            if (id.includes("node_modules/recharts") || id.includes("node_modules/d3-")) return "recharts";
            // exact package names: react-redux and use-sync-external-store belong to Recharts
            if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//.test(id)) return "react";
            return undefined;
          },
        },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
      coverage: {
        provider: "v8",
        reporter: ["text", "lcov"],
        include: ["src/**"],
        exclude: ["src/shared/api/schema.gen.ts", "src/shared/api/contract.check.ts"],
      },
    },
  };
});
