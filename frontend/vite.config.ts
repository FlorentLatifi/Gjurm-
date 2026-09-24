import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

const ROUTES = ["/", "/trends", "/topics", "/entities", "/sources", "/articles", "/about", "/status"];

/** Emits sitemap.xml + robots.txt for the public URL the build targets (VITE_PUBLIC_URL). */
function seoFiles(publicUrl: string | undefined): Plugin {
  return {
    name: "gjurme-seo-files",
    apply: "build",
    transformIndexHtml() {
      // Absolute URLs are only meaningful when the deployment URL is known at build time.
      const base = (publicUrl || "").replace(/\/$/, "");
      if (!/^https?:\/\//.test(base)) return [];
      return [
        { tag: "link", attrs: { rel: "canonical", href: `${base}/` }, injectTo: "head" },
        { tag: "meta", attrs: { property: "og:url", content: `${base}/` }, injectTo: "head" },
        { tag: "meta", attrs: { property: "og:image", content: `${base}/og-image.png` }, injectTo: "head" },
      ];
    },
    generateBundle() {
      const base = (publicUrl || "").replace(/\/$/, "");
      const robots = ["User-agent: *", "Allow: /", "Disallow: /api/"];
      if (base) {
        const today = new Date().toISOString().slice(0, 10);
        const urls = ROUTES.map(
          (r) => `  <url><loc>${base}${r}</loc><lastmod>${today}</lastmod><changefreq>hourly</changefreq></url>`,
        ).join("\n");
        this.emitFile({
          type: "asset",
          fileName: "sitemap.xml",
          source: `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
        });
        robots.push(`Sitemap: ${base}/sitemap.xml`);
      }
      this.emitFile({ type: "asset", fileName: "robots.txt", source: robots.join("\n") + "\n" });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  return {
    plugins: [react(), seoFiles(env.VITE_PUBLIC_URL)],
    server: {
      port: 5173,
      proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" },
    },
    preview: { port: 4173, proxy: { "/api": "http://127.0.0.1:8000" } },
    build: {
      sourcemap: true,
      target: "es2022",
      rollupOptions: {
        output: {
          manualChunks: (id) => {
            if (id.includes("node_modules/recharts") || id.includes("node_modules/d3-")) return "recharts";
            if (id.includes("node_modules/react")) return "react";
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
      coverage: { provider: "v8", reporter: ["text", "lcov"], include: ["src/**"] },
    },
  };
});
