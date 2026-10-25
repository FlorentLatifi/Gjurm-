import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { ArticleList } from "@/features/articles/ArticleList";
import { missingSide, readingCoverage } from "@/features/reading/readingCoverage";
import { ShareStory } from "@/features/stories/ShareStory";
import { StoryCard } from "@/features/stories/StoryCard";
import { StoryCoverage } from "@/features/stories/StoryCoverage";
import type { Coverage, SourceStat, StorySummary } from "@/shared/api/types";
import { availableLenses, biasGroup, blindspotLabel, type Lens, LENSES, noneRated, segments } from "@/shared/model/ratings";
import { useLens } from "@/features/stories/useLens";
import type { Filters } from "@/shared/hooks/useFilters";
import { usePreferences } from "@/stores/preferences";
import { clearReading, recordRead, useReading, useReadingStore } from "@/stores/reading";
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
  summary_sq: "Kuvendi miratoi buxhetin e vitit 2027.",
  image_url: null,
  source_slug: "koha",
  source_name: "KOHA",
  first_published_at: "2026-10-10T08:00:00Z",
  last_published_at: "2026-10-10T12:00:00Z",
  article_count: 5,
  source_count: 4,
  topic_slug: "economy",
  topic_name: "Economy & Business",
  topic_name_sq: "Ekonomi & Biznes",
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

beforeEach(() => {
  localStorage.clear();
  useReadingStore.setState({ entries: [] });
  usePreferences.setState({ theme: "system", lens: null });
});

const NO_FILTERS: Filters = { days: 30, sources: [] };

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
    wrap(<StoryCard story={{ ...story, summary_en: "[headline, no AI summary] x", summary_sq: "[headline, no AI summary] x" }} lens="region" />);
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
    // what another tab (or an earlier visit) wrote is re-read through the store's storage
    act(() => void useReadingStore.persist.rehydrate());
    const { result } = renderHook(() => useReading());
    expect(result.current.map((e) => e.s)).toEqual(["koha"]);
    localStorage.setItem("gjurme-reading", "{not json");
    act(() => void useReadingStore.persist.rehydrate());
    expect(result.current).toEqual([]);
  });

  it("is recorded when an article link is opened", async () => {
    wrap(<ArticleList items={[{
      id: 1, title: "Titulli", url: "https://koha.example/1", published_at: "2026-10-10T08:00:00Z",
      published_at_estimated: false, language: "sq", summary_en: null, summary_sq: null, sentiment_label: null,
      sentiment_score: null, event_type: null, enrichment_status: "succeeded", duplicate_of_id: null,
      story_id: 7, source_slug: "koha", source_name: "KOHA", topic_slug: null, topic_name: null, topic_name_sq: null,
    }]} filters={NO_FILTERS} />);
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
  const router = (entries: string[]) => ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={entries}>{children}</MemoryRouter>
  );
  const unrated: Lens[] = ["region", "ownership"];

  it("defaults to region while nothing is rated, and remembers the reader's choice", () => {
    const { result, rerender } = renderHook(({ available }) => useLens(available), {
      initialProps: { available: unrated as Lens[] | null }, wrapper: router(["/"]),
    });
    expect(result.current[0]).toBe("region");
    rerender({ available: LENSES });
    expect(result.current[0]).toBe("perspective");
    act(() => result.current[1]("ownership"));
    expect(result.current[0]).toBe("ownership");
    expect(JSON.parse(localStorage.getItem("gjurme-prefs")!).state.lens).toBe("ownership");
    // a new view without ?lens= starts from the remembered choice
    const fresh = renderHook(() => useLens(LENSES), { wrapper: router(["/"]) });
    expect(fresh.result.current[0]).toBe("ownership");
  });

  it("lets a shared link's ?lens= win over the remembered choice", () => {
    usePreferences.setState({ lens: "ownership" });
    const { result } = renderHook(() => useLens(LENSES), { wrapper: router(["/stories/7?lens=factuality"]) });
    expect(result.current[0]).toBe("factuality");
    const bogus = renderHook(() => useLens(LENSES), { wrapper: router(["/?lens=<x>"]) });
    expect(bogus.result.current[0]).toBe("ownership");
  });

  it("never splits by a lens with nothing to show, whatever the link or the stored choice", () => {
    usePreferences.setState({ lens: "factuality" });
    const { result } = renderHook(() => useLens(unrated), { wrapper: router(["/?lens=perspective"]) });
    expect(result.current[0]).toBe("region");
  });
});

describe("availableLenses", () => {
  it("offers perspective and factuality only once an outlet in view is rated", () => {
    expect(availableLenses([coverage({ bias: { left: 0, center: 0, right: 0, unrated: 4 }, factuality: { high: 0, mixed: 0, low: 0, unrated: 4 } })]))
      .toEqual(["region", "ownership"]);
    expect(availableLenses([coverage()])).toEqual(LENSES);
  });
});

describe("ShareStory", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("copies the story's address and offers the region's messengers where the device cannot share", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, share: undefined, clipboard: { writeText } });
    wrap(<ShareStory id={42} title="Zgjedhjet & votimi" />);
    const url = `${window.location.origin}/stories/42`;
    await userEvent.click(screen.getByRole("button", { name: "Copy link" }));
    expect(writeText).toHaveBeenCalledWith(url);
    expect(screen.getByRole("status")).toHaveTextContent("Link copied");
    expect(screen.getByRole("link", { name: "WhatsApp" })).toHaveAttribute(
      "href", `https://wa.me/?text=${encodeURIComponent(`Zgjedhjet & votimi ${url}`)}`,
    );
    expect(screen.getByRole("link", { name: "Viber" })).toHaveAttribute("href", expect.stringMatching(/^viber:\/\/forward\?text=/));
    expect(screen.queryByRole("button", { name: "Share" })).toBeNull();
  });

  it("opens the device's share sheet where there is one, and treats closing it as no error", async () => {
    const share = vi.fn().mockRejectedValue(new DOMException("closed", "AbortError"));
    const writeText = vi.fn();
    vi.stubGlobal("navigator", { ...navigator, share, clipboard: { writeText } });
    wrap(<ShareStory id={7} title="Lajmi" />);
    expect(screen.queryByRole("link", { name: "WhatsApp" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Share" }));
    expect(share).toHaveBeenCalledWith({ title: "Lajmi", url: `${window.location.origin}/stories/7` });
    expect(writeText).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});
