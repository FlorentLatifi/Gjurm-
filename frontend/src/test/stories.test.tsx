import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { ArticleList } from "@/features/articles/ArticleList";
import { missingSide, readingCoverage } from "@/features/reading/readingCoverage";
import { StoryCard } from "@/features/stories/StoryCard";
import { StoryCoverage } from "@/features/stories/StoryCoverage";
import type { Coverage, SourceStat, StorySummary } from "@/shared/api/types";
import { biasGroup, blindspotLabel, noneRated, segments } from "@/shared/model/ratings";
import { clearReading, recordRead, useLens, useReading } from "@/stores/reading";
import { CoverageBar } from "@/ui/CoverageBar";

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const coverage = (over: Partial<Coverage> = {}): Coverage => ({
  bias: { left: 1, center: 2, right: 1, unrated: 0 },
  factuality: { high: 3, mixed: 1, low: 0, unrated: 0 },
  ownership: { private: 2, public: 1, nonprofit: 1 },
  region: { XK: 2, AL: 1, RS: 1 },
  ...over,
});

const story: StorySummary = {
  id: 7,
  title: "Kuvendi miraton buxhetin për vitin 2027",
  url: "https://koha.example/1",
  language: "sq",
  summary_en: "Parliament passed the 2027 budget.",
  source_slug: "koha",
  source_name: "KOHA",
  first_published_at: "2026-10-10T08:00:00Z",
  last_published_at: "2026-10-10T12:00:00Z",
  article_count: 5,
  source_count: 4,
  topic_slug: "economy",
  topic_name: "Economy & Business",
  first_source_slug: "koha",
  first_source_name: "KOHA",
  coverage: coverage(),
  tone: { negative: 1, neutral: 3, positive: 1 },
  sources: [
    { slug: "koha", name: "KOHA", bias: "center", country: "XK" },
    { slug: "majtas", name: "Majtas Lajme", bias: "lean_left", country: "XK" },
  ],
  blindspots: [{ kind: "region", missing: "AL" }],
};

beforeEach(() => localStorage.clear());

describe("coverage segments", () => {
  it("folds perspective into left / center / right / unrated in a fixed order", () => {
    const parts = segments(coverage({ bias: { left: 0, center: 1, right: 3, unrated: 2 } }), "perspective");
    expect(parts.map((p) => [p.key, p.value])).toEqual([["left", 0], ["center", 1], ["right", 3], ["unrated", 2]]);
    expect(parts.find((p) => p.key === "unrated")?.hatched).toBe(true);
  });

  it("gives every followed country a fixed slot and folds the rest into Other", () => {
    const parts = segments(coverage(), "region");
    expect(parts.map((p) => p.key)).toEqual(["XK", "AL", "MK", "REG", "other"]);
    expect(parts.find((p) => p.key === "other")?.value).toBe(1);
  });

  it("knows when nothing is rated", () => {
    expect(noneRated([coverage({ bias: { left: 0, center: 0, right: 0, unrated: 4 } })])).toBe(true);
    expect(noneRated([coverage()])).toBe(false);
    expect(biasGroup("lean_right")).toBe("right");
    expect(blindspotLabel({ kind: "perspective", missing: "left" })).toMatch(/few left-leaning/);
    expect(blindspotLabel({ kind: "region", missing: "AL" })).toMatch(/from Albania/);
  });
});

describe("CoverageBar", () => {
  it("states every share as text, not only as colour", () => {
    wrap(<StoryCoverage coverage={coverage()} lens="perspective" />);
    const bar = screen.getByRole("img");
    expect(bar).toHaveAccessibleName(
      "Coverage by perspective. Left: 1 outlet (25%), Center: 2 outlets (50%), Right: 1 outlet (25%).",
    );
    expect(screen.getByText("Center")).toBeInTheDocument();
    expect(screen.queryByText("Unrated")).not.toBeInTheDocument(); // 0 unrated: no label
  });

  it("handles a story without coverage data", () => {
    wrap(<CoverageBar parts={[]} caption="x" />);
    expect(screen.getByText("No coverage data")).toBeInTheDocument();
  });
});

describe("StoryCard", () => {
  it("links to the story page and shows outlets, first report and blindspots", () => {
    wrap(<StoryCard story={story} lens="perspective" />);
    expect(screen.getByRole("link", { name: story.title })).toHaveAttribute("href", "/stories/7");
    expect(screen.getByText("4 outlets")).toBeInTheDocument();
    expect(screen.getByText(/First: KOHA/)).toBeInTheDocument();
    expect(screen.getByText("Blindspot: no outlet from Albania covered this")).toBeInTheDocument();
    expect(screen.getByText("Parliament passed the 2027 budget.")).toBeInTheDocument();
  });

  it("hides the placeholder summary of keyword-rule analysis", () => {
    wrap(<StoryCard story={{ ...story, summary_en: "[headline, no AI summary] x" }} lens="region" />);
    expect(screen.queryByText(/no AI summary/)).not.toBeInTheDocument();
  });
});

describe("reading log (My news bias)", () => {
  it("records opened articles in this browser only and can be cleared", async () => {
    const { result } = renderHook(() => useReading());
    expect(result.current).toEqual([]);
    act(() => recordRead("koha", 7, "economy"));
    expect(result.current).toHaveLength(1);
    expect(result.current[0]).toMatchObject({ s: "koha", st: 7, t: "economy" });
    act(() => clearReading());
    expect(result.current).toEqual([]);
    expect(localStorage.getItem("gjurme-reading")).toBeNull();
  });

  it("ignores corrupt or stale entries", () => {
    localStorage.setItem(
      "gjurme-reading",
      JSON.stringify([{ s: "<script>", at: Date.now() }, { s: "koha", at: 1 }, { s: "koha", at: Date.now() }]),
    );
    const { result } = renderHook(() => useReading());
    expect(result.current.map((e) => e.s)).toEqual(["koha"]);
    localStorage.setItem("gjurme-reading", "{not json");
    const again = renderHook(() => useReading());
    expect(again.result.current).toEqual([]);
  });

  it("is recorded when an article link is opened", async () => {
    wrap(<ArticleList items={[{
      id: 1, title: "Titulli", url: "https://koha.example/1", published_at: "2026-10-10T08:00:00Z",
      published_at_estimated: false, language: "sq", summary_en: null, sentiment_label: null,
      sentiment_score: null, event_type: null, enrichment_status: "succeeded", duplicate_of_id: null,
      story_id: 7, source_slug: "koha", source_name: "KOHA", topic_slug: null, topic_name: null,
    }]} />);
    expect(screen.getByRole("link", { name: "All coverage of: Titulli" })).toHaveAttribute("href", "/stories/7");
    const link = screen.getByRole("link", { name: /^Titulli/ });
    link.addEventListener("click", (e) => e.preventDefault()); // jsdom cannot open new tabs
    await userEvent.click(link);
    expect(JSON.parse(localStorage.getItem("gjurme-reading")!)[0]).toMatchObject({ s: "koha", st: 7 });
  });

  it("summarises the balance and finds the blind side", () => {
    const sources = new Map<string, SourceStat>(
      [["l", "left", "XK"], ["c", "center", "AL"], ["r", "right", "XK"]].map(([slug, bias, country]) => [
        slug!,
        { slug, bias, country, factuality: "high", ownership: "private" } as unknown as SourceStat,
      ]),
    );
    const entries = ["l", "l", "l", "l", "c", "unknown-outlet"].map((s) => ({ s, st: null, t: null, at: Date.now() }));
    const cov = readingCoverage(entries, sources);
    expect(cov.bias).toEqual({ left: 4, center: 1, right: 0, unrated: 1 });
    expect(cov.region).toEqual({ XK: 4, AL: 1, other: 1 });
    expect(missingSide(cov)).toBe("right");
    expect(missingSide(readingCoverage(entries.slice(0, 3), sources))).toBeNull(); // too few
  });
});

describe("useLens", () => {
  it("defaults to region while nothing is rated, and remembers the reader's choice", () => {
    const { result, rerender } = renderHook(({ none }) => useLens(none), { initialProps: { none: true } });
    expect(result.current[0]).toBe("region");
    rerender({ none: false });
    expect(result.current[0]).toBe("perspective");
    act(() => result.current[1]("ownership"));
    expect(result.current[0]).toBe("ownership");
    expect(localStorage.getItem("gjurme-lens")).toBe("ownership");
  });
});
