import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { useTitle } from "@/shared/hooks/useTitle";
import { useApiQuery } from "@/shared/query/apiQuery";
import { ENTITY_TYPE_LABEL, formatInt } from "@/shared/lib/format";
import { countryLabel, noneRated, REGION_ORDER } from "@/shared/model/ratings";
import { useReadingCount } from "@/stores/reading";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { SearchField } from "@/ui/SearchField";

import { loadStoryPage, StoryCard } from "../StoryCard";
import { LensPicker } from "../StoryCoverage";
import { useLens } from "../useLens";
import { FEED_DEFAULT_DAYS, feedQueries, feedState } from "../queries";

export const FEED_PRESETS = [
  { days: 1, label: "Today" },
  { days: 3, label: "3 days" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
] as const;

/**
 * The home page, as on Ground News: the news grouped into stories, biggest first, each with a
 * bar showing how its coverage splits across outlets — plus blindspots and trending names.
 */
export default function StoriesPage() {
  useTitle("", "Albanian and Balkan news grouped into stories, with how each outlet covered them.");
  const { filters } = useFilters(FEED_DEFAULT_DAYS);
  const [params, setParams] = useSearchParams();
  const ids = { topic: useId(), region: useId(), q: useId(), panel: useId() };
  const [filtersOpen, setFiltersOpen] = useState(false);
  const { sort, topic, country, q, page } = feedState(params);
  const queries = feedQueries(params);
  const taxonomy = useApiQuery(queries.taxonomy);

  const set = (key: string, value: string) =>
    setParams((prev) => {
      const out = new URLSearchParams(prev);
      if (value) out.set(key, value);
      else out.delete(key);
      if (key !== "page") out.delete("page");
      return out;
    });


  const stories = useApiQuery(queries.stories);
  const blind = useApiQuery(queries.blindspots);
  const spikes = useApiQuery(queries.spikes);
  const readCount = useReadingCount();
  useEffect(() => {
    // the next page a reader of the feed most likely opens: fetch its code while idle
    const idle = window.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 1500));
    idle(() => void loadStoryPage());
  }, []);
  const items = stories.data?.items ?? [];
  const [lens, setLens] = useLens(stories.data ? noneRated(items.map((s) => s.coverage)) : false);
  const data = stories.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Top stories</h1>
          <p>
            The same event as reported by different outlets, grouped into one story. The bar shows
            who covered it — by perspective, region, ownership or factuality of the outlets.{" "}
            <Link to="/about#stories">How stories and ratings work</Link>
          </p>
        </div>
      </div>
      <FilterBar presets={FEED_PRESETS} defaultDays={FEED_DEFAULT_DAYS} />
      <div className="filters" role="group" aria-label="Story filters">
        <div className="segmented" role="group" aria-label="Order">
          <button type="button" aria-pressed={sort === "top"} onClick={() => set("sort", "")}>Most covered</button>
          <button type="button" aria-pressed={sort === "latest"} onClick={() => set("sort", "latest")}>Latest</button>
        </div>
        {/* on a phone the secondary filters fold away, so the stories start on the first screen */}
        <button type="button" className="btn btn--sm filters__toggle" aria-expanded={filtersOpen}
          aria-controls={ids.panel} onClick={() => setFiltersOpen((o) => !o)}>
          Filter stories{[topic, country, q].filter(Boolean).length ? ` (${[topic, country, q].filter(Boolean).length})` : ""}
        </button>
        <div id={ids.panel} className={`filters__panel ${filtersOpen ? "is-open" : ""}`}>
          <div className="field">
            <label htmlFor={ids.topic}>Topic</label>
            <select id={ids.topic} value={topic} onChange={(e) => set("topic", e.target.value)}>
              <option value="">All topics</option>
              {taxonomy.data?.map((t) => <option key={t.slug} value={t.slug}>{t.name_en}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor={ids.region}>Covered by outlets from</label>
            <select id={ids.region} value={country} onChange={(e) => set("country", e.target.value)}>
              <option value="">Anywhere</option>
              {REGION_ORDER.map((c) => <option key={c} value={c}>{countryLabel(c)}</option>)}
            </select>
          </div>
          <SearchField id={ids.q} label="Search stories" value={q} onCommit={(v) => set("q", v)}
            placeholder="e.g. buxheti, Prizren, KQZ" />
        </div>
      </div>
      <div className="lens-row">
        <span className="rank-meta">Split coverage by</span>
        <LensPicker lens={lens} onChange={setLens} />
      </div>

      <div className="feed-layout">
        <section aria-labelledby="feed-heading">
          <h2 id="feed-heading" className="visually-hidden">Stories</h2>
          <Card title={data ? `${formatInt(data.total)} ${data.total === 1 ? "story" : "stories"}` : "Stories"}
            query={stories} empty={!items.length}
            emptyText={q ? "No story matches this search." : "No story was covered by two or more outlets in this period yet. Try a longer period."}>
            {() => (
              <>
                <ol className="story-list">
                  {items.map((s, i) => (
                    <li key={s.id}>
                      <StoryCard story={s} lens={lens} lead={i === 0 && page === 1 && sort === "top" && !q} />
                    </li>
                  ))}
                </ol>
                {data!.pages > 1 && (
                  <nav className="pagination" aria-label="Pagination">
                    <button type="button" className="btn btn--sm" disabled={page <= 1}
                      onClick={() => set("page", String(page - 1))}>← Previous</button>
                    <span aria-live="polite">Page {data!.page} of {data!.pages}</span>
                    <button type="button" className="btn btn--sm" disabled={page >= data!.pages || page >= 200}
                      onClick={() => set("page", String(page + 1))}>Next →</button>
                  </nav>
                )}
              </>
            )}
          </Card>
        </section>

        <aside className="feed-aside" aria-label="More">
          <Card title="Blindspot" question="Stories one side — or one country's outlets — barely covered."
            query={blind} empty={!blind.data?.items.length}
            emptyText="No blindspot in this period."
            actions={<Link className="btn btn--ghost btn--sm" to="/blindspot" aria-label="All blindspots">See all</Link>}>
            {() => (
              <div>
                {blind.data!.items.slice(0, 3).map((s) => <StoryCard key={s.id} story={s} lens="perspective" compact />)}
              </div>
            )}
          </Card>
          <Card title="My news bias" question="Which outlets you read here, by perspective and region.">
            {() => (
              <p className="card__question mt-0">
                {readCount
                  ? <>You opened {readCount} {readCount === 1 ? "article" : "articles"} recently. </>
                  : <>Open articles from the stories to see the balance of your reading. </>}
                <Link to="/my-news">See your balance →</Link> Stored only in this browser.
              </p>
            )}
          </Card>
          <Card title="Trending names" question="People and organisations suddenly in the news (24 h)."
            query={spikes} empty={!spikes.data?.items.length} emptyText="Not enough history yet.">
            {() => (
              <RankList unit="mentions" items={spikes.data!.items.slice(0, 6).map((e) => ({
                key: e.id, label: e.name, href: withFilters(`/entities/${e.id}`, { ...filters, days: 30 }),
                value: e.last_24h, sublabel: ENTITY_TYPE_LABEL[e.type],
              }))} />
            )}
          </Card>
        </aside>
      </div>
    </>
  );
}
