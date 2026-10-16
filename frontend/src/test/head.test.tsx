import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useTitle } from "@/shared/hooks/useTitle";

function at(url: string) {
  return ({ children }: { children: ReactNode }) => <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>;
}
const head = (selector: string, attr = "content") => document.head.querySelector(selector)?.getAttribute(attr);

describe("useTitle", () => {
  it("gives each page its own canonical URL (without filters) and Open Graph twin", () => {
    renderHook(() => useTitle("Story", "4 outlets covered this story."), { wrapper: at("/stories/42?lens=region") });
    expect(document.title).toBe("Story · GJURMË");
    expect(head('link[rel="canonical"]', "href")).toBe(`${window.location.origin}/stories/42`);
    expect(head('meta[property="og:url"]')).toBe(`${window.location.origin}/stories/42`);
    expect(head('meta[name="description"]')).toBe("4 outlets covered this story.");
    expect(head('meta[property="og:title"]')).toBe("Story · GJURMË");
    expect(document.head.querySelectorAll('link[rel="canonical"]')).toHaveLength(1);
  });

  it("restores the site description on a page without one", () => {
    renderHook(() => useTitle("A", "Specific."), { wrapper: at("/a") });
    renderHook(() => useTitle("B"), { wrapper: at("/b") });
    expect(head('meta[name="description"]')).not.toBe("Specific.");
  });

  it("asks search engines not to list a not-found page, and only that page", () => {
    const { unmount } = renderHook(() => useTitle("Not found", undefined, { index: false }), {
      wrapper: at("/stories/999999"),
    });
    expect(head('meta[name="robots"]')).toBe("noindex");
    unmount();
    renderHook(() => useTitle("Topics"), { wrapper: at("/topics") });
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull();
  });
});
