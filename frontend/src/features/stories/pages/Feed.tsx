import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { useTitle } from "@/shared/hooks/useTitle";
import { useApiQuery } from "@/shared/query/apiQuery";
import { ENTITY_TYPE_LABEL } from "@/shared/lib/format";
import { availableLenses, countryLabel, REGION_ORDER } from "@/shared/model/ratings";
import { useReadingCount } from "@/stores/reading";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { SearchField } from "@/ui/SearchField";

import { loadStoryPage, StoryCard } from "../StoryCard";
import { LensPicker } from "../StoryCoverage";
import { useLens } from "../useLens";
import { FEED_DEFAULT_DAYS, feedQueries, feedState } from "../queries";
import { localName, t, tn } from "@/shared/i18n";

export const FEED_PRESETS = [1, 3, 7, 30] as const;

/**
 * The home page, as on Ground News: the news grouped into stories, biggest first, each with a
 * bar showing how its coverage splits across outlets — plus blindspots and trending names.
 */
export default function StoriesPage() {
  useTitle("", t("Albanian and Balkan news grouped into stories, with how each outlet covered them."));
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
  const available = stories.data ? availableLenses(items.map((s) => s.coverage)) : null;
  const [lens, setLens] = useLens(available);
  // the blindspot box: perspective bars only once its stories have rated outlets
  const blindLens = availableLenses((blind.data?.items ?? []).map((s) => s.coverage)).includes("perspective")
    ? "perspective"
    : "region";
  const data = stories.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("Top stories")}</h1>
          <p>
            {t("The same event as reported by different outlets, grouped into one story. The bar shows who covered it — by perspective, region, ownership or factuality of the outlets.")}{" "}
            <Link to="/about#stories">{t("How stories and ratings work")}</Link>
          </p>
        </div>
      </div>
      <FilterBar presets={FEED_PRESETS} defaultDays={FEED_DEFAULT_DAYS} />
      <div className="filters" role="group" aria-label={t("Story filters")}>
        <div className="segmented" role="group" aria-label={t("Order")}>
          <button type="button" aria-pressed={sort === "top"} onClick={() => set("sort", "")}>{t("Most covered")}</button>
          <button type="button" aria-pressed={sort === "latest"} onClick={() => set("sort", "latest")}>{t("Latest")}</button>
        </div>
        {/* on a phone the secondary filters fold away, so the stories start on the first screen */}
        <button type="button" className="btn btn--sm filters__toggle" aria-expanded={filtersOpen}
          aria-controls={ids.panel} onClick={() => setFiltersOpen((o) => !o)}>
          {t("Filter stories")}{[topic, country, q].filter(Boolean).length ? ` (${[topic, country, q].filter(Boolean).length})` : ""}
        </button>
        <div id={ids.panel} className={`filters__panel ${filtersOpen ? "is-open" : ""}`}>
          <div className="field">
            <label htmlFor={ids.topic}>{t("Topic")}</label>
            <select id={ids.topic} value={topic} onChange={(e) => set("topic", e.target.value)}>
              <option value="">{t("All topics")}</option>
              {taxonomy.data?.map((tp) => <option key={tp.slug} value={tp.slug}>{localName(tp.name_en, tp.name_sq)}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor={ids.region}>{t("Covered by outlets from")}</label>
            <select id={ids.region} value={country} onChange={(e) => set("country", e.target.value)}>
              <option value="">{t("Anywhere")}</option>
              {REGION_ORDER.map((c) => <option key={c} value={c}>{countryLabel(c)}</option>)}
            </select>
          </div>
          <SearchField id={ids.q} label={t("Search stories")} value={q} onCommit={(v) => set("q", v)}
            placeholder={t("e.g. buxheti, Prizren, KQZ")} />
        </div>
      </div>
      <div className="lens-row">
        <span className="rank-meta">{t("Split coverage by")}</span>
        <LensPicker lens={lens} onChange={setLens} available={available ?? undefined} />
      </div>

      <div className="feed-layout">
        <section aria-labelledby="feed-heading">
          <h2 id="feed-heading" className="visually-hidden">{t("Stories")}</h2>
          <Card title={data ? tn(data.total, "{n} story", "{n} stories") : t("Stories")}
            query={stories} empty={!items.length}
            emptyText={q ? t("No story matches this search.") : t("No story was covered by two or more outlets in this period yet. Try a longer period.")}>
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
                  <nav className="pagination" aria-label={t("Pagination")}>
                    <button type="button" className="btn btn--sm" disabled={page <= 1}
                      onClick={() => set("page", String(page - 1))}>← {t("Previous")}</button>
                    <span aria-live="polite">{t("Page {page} of {pages}", { page: data!.page, pages: data!.pages })}</span>
                    <button type="button" className="btn btn--sm" disabled={page >= data!.pages || page >= 200}
                      onClick={() => set("page", String(page + 1))}>{t("Next")} →</button>
                  </nav>
                )}
              </>
            )}
          </Card>
        </section>

        <aside className="feed-aside" aria-label={t("More")}>
          <Card title={t("Blindspot")} question={t("Stories one side — or one country's outlets — barely covered.")}
            query={blind} empty={!blind.data?.items.length}
            emptyText={t("No blindspot in this period.")}
            actions={<Link className="btn btn--ghost btn--sm" to="/blindspot" aria-label={t("All blindspots")}>{t("See all")}</Link>}>
            {() => (
              <div>
                {blind.data!.items.slice(0, 3).map((s) => <StoryCard key={s.id} story={s} lens={blindLens} compact />)}
              </div>
            )}
          </Card>
          <Card title={t("My news bias")} question={t("Which outlets you read here, by perspective and region.")}>
            {() => (
              <p className="card__question mt-0">
                {readCount
                  ? tn(readCount, "You opened {n} article recently.", "You opened {n} articles recently.")
                  : t("Open articles from the stories to see the balance of your reading.")}{" "}
                <Link to="/my-news">{t("See your balance")} →</Link> {t("Stored only in this browser.")}
              </p>
            )}
          </Card>
          <Card title={t("Trending names")} question={t("People and organisations suddenly in the news (24 h).")}
            query={spikes} empty={!spikes.data?.items.length} emptyText={t("Not enough history yet.")}>
            {() => (
              <RankList unit={(n) => tn(n, "{n} mention", "{n} mentions")} items={spikes.data!.items.slice(0, 6).map((e) => ({
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
