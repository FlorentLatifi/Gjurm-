import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const SITE_TITLE = "GJURMË — every side of the Albanian-language news";
// index.html's description, for pages that have none of their own (the previous page's would
// otherwise stay in place after client-side navigation).
const DEFAULT_DESCRIPTION =
  document.querySelector('meta[name="description"]')?.getAttribute("content") ?? "";
// Absolute URLs need the public address; VITE_PUBLIC_URL is set at image build time.
const PUBLIC_URL = (
  /^https?:\/\//.test(import.meta.env.VITE_PUBLIC_URL ?? "") ? import.meta.env.VITE_PUBLIC_URL! : window.location.origin
).replace(/\/$/, "");

function headElement(selector: string, create: () => HTMLElement): HTMLElement {
  let el = document.head.querySelector<HTMLElement>(selector);
  if (!el) {
    el = create();
    document.head.appendChild(el);
  }
  return el;
}

function setMeta(attr: "name" | "property", key: string, content: string | null) {
  const selector = `meta[${attr}="${key}"]`;
  if (content === null) {
    document.head.querySelector(selector)?.remove();
    return;
  }
  headElement(selector, () => {
    const meta = document.createElement("meta");
    meta.setAttribute(attr, key);
    return meta;
  }).setAttribute("content", content);
}

/**
 * The page's head: title, description, canonical URL and their Open Graph twins.
 * The canonical URL is the path without its query: filters and paging are views of one page.
 * ``index: false`` (not-found pages) asks search engines not to list the URL; the server answers
 * 200 for every route of the single-page app, so this is how a 404 reaches them.
 */
export function useTitle(title: string, description?: string, { index = true }: { index?: boolean } = {}) {
  const { pathname } = useLocation();
  useEffect(() => {
    const fullTitle = title ? `${title} · GJURMË` : SITE_TITLE;
    const text = description ?? DEFAULT_DESCRIPTION;
    const url = PUBLIC_URL + pathname;
    document.title = fullTitle;
    setMeta("name", "description", text);
    setMeta("property", "og:title", fullTitle);
    setMeta("property", "og:description", text);
    setMeta("property", "og:url", url);
    setMeta("name", "robots", index ? null : "noindex");
    headElement('link[rel="canonical"]', () => {
      const link = document.createElement("link");
      link.rel = "canonical";
      return link;
    }).setAttribute("href", url);
  }, [title, description, index, pathname]);
}
