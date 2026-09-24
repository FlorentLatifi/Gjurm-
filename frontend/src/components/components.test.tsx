import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { ApiError } from "../api/client";
import type { ArticleSummary, PublicStatus } from "../api/types";
import { Card } from "./Card";
import { Layout } from "./Layout";
import { SentimentBar } from "./charts";
import { ArticleList, RankList } from "./lists";
import { StatTile } from "./StatTile";

function wrap(ui: ReactNode, route = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const baseQuery = { isPending: false, isError: false, error: null, refetch: vi.fn() };

describe("Card states", () => {
  it("shows a loading status while pending", () => {
    wrap(<Card title="Volume" query={{ ...baseQuery, isPending: true }}>{() => <p>chart</p>}</Card>);
    expect(screen.getByRole("status")).toHaveTextContent("Loading Volume");
    expect(screen.queryByText("chart")).not.toBeInTheDocument();
  });

  it("shows API errors with a retry button", async () => {
    const refetch = vi.fn();
    const error = new ApiError(429, "rate_limited", "slow down", 12);
    wrap(<Card title="Volume" query={{ ...baseQuery, isError: true, error, refetch }}>{() => <p>chart</p>}</Card>);
    expect(screen.getByRole("alert")).toHaveTextContent("please wait 12 seconds");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows the empty state", () => {
    wrap(<Card title="Volume" query={baseQuery} empty emptyText="Nothing yet">{() => <p>chart</p>}</Card>);
    expect(screen.getByText("Nothing yet")).toBeInTheDocument();
  });

  it("toggles between chart and table views", async () => {
    wrap(
      <Card title="Volume" question="Is it rising?" method="Daily counts." query={baseQuery}
        table={() => <table><tbody><tr><td>table view</td></tr></tbody></table>}>
        {() => <p>chart view</p>}
      </Card>,
    );
    expect(screen.getByRole("region", { name: "Volume" })).toBeInTheDocument();
    expect(screen.getByText("Is it rising?")).toBeInTheDocument();
    expect(screen.getByText("Daily counts.")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Table" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    expect(screen.getByText("table view")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chart" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("StatTile", () => {
  it("renders value, delta direction and sub-label", () => {
    wrap(<StatTile label="Articles today" value="92" delta={0.1} deltaLabel="vs yesterday" upIsGood sub="5 outlets" />);
    expect(screen.getByText("92")).toBeInTheDocument();
    expect(screen.getByText(/\+10% vs yesterday/)).toHaveClass("delta--up");
  });

  it("neutral deltas are not coloured good or bad", () => {
    wrap(<StatTile label="x" value="1" delta={-0.2} upIsGood={null} />);
    expect(screen.getByText(/−20%/)).toHaveClass("delta--flat");
  });
});

const article = (over: Partial<ArticleSummary>): ArticleSummary => ({
  id: 1,
  title: "Kuvendi miraton buxhetin",
  url: "https://www.koha.net/lajme/1",
  published_at: "2026-09-24T10:00:00Z",
  published_at_estimated: false,
  language: "sq",
  summary_en: "Parliament approved the budget.",
  sentiment_label: "neutral",
  sentiment_score: 0,
  event_type: "policy_decision",
  enrichment_status: "succeeded",
  duplicate_of_id: null,
  source_slug: "koha",
  source_name: "KOHA",
  topic_slug: "politics",
  topic_name: "Politics & Government",
  ...over,
});

describe("ArticleList", () => {
  it("links headlines to the original publisher safely, with attribution", () => {
    wrap(<ArticleList items={[article({})]} />);
    const link = screen.getByRole("link", { name: /^Kuvendi miraton buxhetin/ });
    expect(link).toHaveAttribute("href", "https://www.koha.net/lajme/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("lang", "sq");
    expect(screen.getByText("KOHA")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Politics & Government" })).toHaveAttribute("href", "/topics/politics");
  });

  it("never renders dangerous URLs as links and never interprets markup", () => {
    wrap(<ArticleList items={[article({ url: "javascript:alert(1)", title: "<img src=x onerror=alert(1)>" })]} />);
    expect(screen.queryByRole("link", { name: /^<img/ })).not.toBeInTheDocument();
    // the internal details link has a descriptive accessible name
    expect(screen.getByRole("link", { name: /^Analysis details for: <img/ })).toHaveAttribute("href", "/articles/1");
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img[src='x']")).toBeNull();
  });

  it("marks estimated dates and syndicated copies", () => {
    wrap(<ArticleList items={[article({ published_at_estimated: true, duplicate_of_id: 7 })]} />);
    expect(screen.getByText("(est.)")).toBeInTheDocument();
    expect(screen.getByText("Also reported elsewhere")).toBeInTheDocument();
  });
});

describe("RankList & SentimentBar", () => {
  it("renders ranked items with proportional bars", () => {
    wrap(<RankList unit="articles" items={[
      { key: "a", label: "Politics", value: 10, href: "/topics/politics" },
      { key: "b", label: "Sports", value: 5 },
    ]} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByRole("link", { name: "Politics" })).toBeInTheDocument();
    expect(items[1]!.querySelector(".rank-bar")).toHaveStyle({ width: "50%" });
  });

  it("describes the tone mix in text for screen readers", () => {
    render(<SentimentBar negative={1} neutral={2} positive={1} />);
    expect(screen.getByRole("img")).toHaveAccessibleName("25% negative, 50% neutral, 25% positive");
  });
});

describe("Analysis disclosure banner", () => {
  const status = (analysis: PublicStatus["analysis"], demo = false): PublicStatus => ({
    status: "ok",
    last_run_at: null,
    last_run_status: "succeeded",
    last_success_at: new Date().toISOString(),
    minutes_since_success: 3,
    scheduler_heartbeat_at: null,
    articles_last_24h: 10,
    enrichment_backlog: 0,
    sources: [],
    analysis,
    demo_data: demo,
    version: "test",
  });
  const serve = (body: PublicStatus) =>
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })));
  afterEach(() => vi.unstubAllGlobals());

  it("says plainly when recent articles were analysed by keyword rules", async () => {
    serve(status({ mode: "mixed", rule_based_share: 0.25, model: "claude-sonnet-5" }));
    wrap(<Layout />);
    expect(await screen.findByText(/25% of recent articles were analysed by keyword rules/)).toBeInTheDocument();
  });

  it("is absent when an AI model did the analysis", async () => {
    serve(status({ mode: "ai", rule_based_share: 0, model: "claude-sonnet-5" }));
    wrap(<Layout />);
    await screen.findAllByText(/updated/i);
    expect(screen.queryByText(/keyword rules/)).not.toBeInTheDocument();
  });
});
