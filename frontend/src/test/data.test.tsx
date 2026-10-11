import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import type { LoaderFunctionArgs } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "@/app/queryClient";
import { routes } from "@/app/router";
import { feedQueries } from "@/features/stories/queries";
import { apiQuery, useApiQuery } from "@/shared/query/apiQuery";

function json(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
}

describe("route loaders", () => {
  const fetchMock = vi.fn((input: RequestInfo | URL) => json({ url: String(input) }));
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    queryClient.clear();
    fetchMock.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  const loaderFor = (path: string | undefined, index = false) => {
    const children = routes[0]!.children!;
    const route = children.find((r) => (index ? r.index : r.path === path))!;
    return route.loader as (args: LoaderFunctionArgs) => unknown;
  };
  const args = (url: string, params: Record<string, string> = {}) =>
    ({ request: new Request(`http://localhost${url}`), params, context: undefined }) as unknown as LoaderFunctionArgs;

  it("start the page's requests without waiting for them", () => {
    const result = loaderFor("stories/:id")(args("/stories/42", { id: "42" }));
    expect(result).toBeNull(); // navigation is never held behind the network
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/stories/42", expect.anything());
  });

  it("prefetch exactly the cache entries the page reads", async () => {
    loaderFor(undefined, true)(args("/?days=7&sort=latest&q=Prizren"));
    const page = feedQueries(new URLSearchParams("days=7&sort=latest&q=Prizren"));
    await waitFor(() => expect(queryClient.getQueryData(page.stories.queryKey)).toBeDefined());
    expect(queryClient.getQueryData(page.blindspots.queryKey)).toBeDefined();
    expect(queryClient.getQueryData(page.taxonomy.queryKey)).toBeDefined();
  });

  it("do not ask the API about ids that cannot exist", () => {
    loaderFor("stories/:id")(args("/stories/abc", { id: "abc" }));
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
