import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "@/app/queryClient";
import { prefetchRoute } from "@/app/router";
import { feedQueries } from "@/features/stories/queries";
import { apiQuery, useApiQuery } from "@/shared/query/apiQuery";

function json(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
}

describe("route prefetch", () => {
  const fetchMock = vi.fn((input: RequestInfo | URL) => json({ url: String(input) }));
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    queryClient.clear();
    fetchMock.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  const at = (url: string) => {
    const u = new URL(`http://localhost${url}`);
    return { pathname: u.pathname, search: u.search };
  };

  it("starts the page's requests at once, without waiting for them", () => {
    expect(prefetchRoute(queryClient, at("/stories/42"))).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/stories/42", expect.anything());
  });

  it("fills exactly the cache entries the page reads", async () => {
    prefetchRoute(queryClient, at("/?days=7&sort=latest&q=Prizren"));
    const page = feedQueries(new URLSearchParams("days=7&sort=latest&q=Prizren"));
    await waitFor(() => expect(queryClient.getQueryData(page.stories.queryKey)).toBeDefined());
    expect(queryClient.getQueryData(page.blindspots.queryKey)).toBeDefined();
    expect(queryClient.getQueryData(page.taxonomy.queryKey)).toBeDefined();
  });

  it("does not ask the API about ids that cannot exist, or about unknown pages", () => {
    expect(prefetchRoute(queryClient, at("/stories/abc"))).toBe(false);
    expect(prefetchRoute(queryClient, at("/no-such-page"))).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("useApiQuery", () => {
  afterEach(() => vi.unstubAllGlobals());

  function setup() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    let release: (() => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("days=7") || url.includes("/stories/2")) {
        return new Promise<Response>((resolve) => {
          release = () => void json({ url }).then(resolve);
        });
      }
      return json({ url });
    }));
    return { wrapper, release: () => release?.() };
  }

  it("keeps the previous result while the same resource refetches with new filters", async () => {
    const { wrapper } = setup();
    const { result, rerender } = renderHook(({ days }) => useApiQuery(apiQuery<{ url: string }>("/api/v1/x", { days }, "feed")), {
      wrapper, initialProps: { days: 3 },
    });
    await waitFor(() => expect(result.current.data?.url).toContain("days=3"));
    rerender({ days: 7 });
    expect(result.current.isPlaceholderData).toBe(true);
    expect(result.current.data?.url).toContain("days=3");
  });

  it("never shows another resource's data while a new one loads", async () => {
    const { wrapper } = setup();
    const { result, rerender } = renderHook(({ id }) => useApiQuery(apiQuery<{ url: string }>(`/api/v1/stories/${id}`, undefined, "feed")), {
      wrapper, initialProps: { id: 1 },
    });
    await waitFor(() => expect(result.current.data?.url).toContain("/stories/1"));
    rerender({ id: 2 });
    expect(result.current.data).toBeUndefined();
    expect(result.current.isPending).toBe(true);
  });
});
