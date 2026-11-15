import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { FilterBar, SourceSelect } from "@/features/filters";
import { readFilters } from "@/shared/hooks/useFilters";
import { useTitle } from "@/shared/hooks/useTitle";
import { useApiQuery } from "@/shared/query/apiQuery";
import { availableLenses, countryLabel, REGION_ORDER } from "@/shared/model/ratings";
import { useReadingCount } from "@/stores/reading";
import "@/ui/card.css";
import { SearchField } from "@/ui/SearchField";
import { EmptyState, ErrorState, LoadingBlock } from "@/ui/States";

import { BlindspotCard, HeroStory, loadStoryPage, StoryLine, StoryRow } from "../StoryCard";
import { LensPicker } from "../StoryCoverage";
import { useLens } from "../useLens";
import { FEED_DEFAULT_DAYS, feedQueries, feedState } from "../queries";
import { localName, t, tn } from "@/shared/i18n";

export const FEED_PRESETS = [1, 3, 7, 30] as const;
/** How many stories sit in columns under the lead, before the side column on a phone. */
const TOP = 3;

/**
 * The front page, set as a newspaper's: the lead story across the top with its coverage, the
 * next stories in columns under it, the blindspots, the reader's own balance and the latest
 * stories in a side column, then the rest of the feed. Every story shows how its coverage splits.
 */
export default function StoriesPage() {
  useTitle("", t("Albanian and Balkan news grouped into stories, with how each outlet covered them."));
  const [params, setParams] = useSearchParams();
  const ids = { topic: useId(), region: useId(), q: useId(), panel: useId() };
  const [filtersOpen, setFiltersOpen] = useState(false);
  const { sort, topic, country, q, page } = feedState(params);
  const { days } = readFilters(params, FEED_DEFAULT_DAYS);
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
  const latest = useApiQuery(queries.latest);
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
  // the blindspot column: perspective bars only once its stories have rated outlets
  const blindLens = availableLenses((blind.data?.items ?? []).map((s) => s.coverage)).includes("perspective")
    ? "perspective"
    : "region";
  const latestLens = availableLenses((latest.data?.items ?? []).map((s) => s.coverage)).includes(lens) ? lens : "region";
  const data = stories.data;
  // the lead: the most covered story on the first page of the unfiltered "most covered" feed
  const leads = page === 1 && sort === "top" && !q && items.length > 0;
  const [hero, ...rest] = leads ? items : [undefined, ...items];
  const list = rest.filter((s) => s !== undefined);
  const activeFilters = [topic, country, q].filter(Boolean).length;
  // names suddenly in the news: decoration, so whatever the API answers it never breaks the page
  const names = Array.isArray(spikes.data?.items) ? spikes.data.items : [];
  const refetching = stories.isPlaceholderData && stories.isFetching ? "card--refetching" : undefined;

  return (
    <>
      <h1 className="visually-hidden">{t("Top stories")}</h1>
      <div className={`feed-toolbar ${filtersOpen ? "is-open" : ""}`} role="group" aria-label={t("Story filters")}>
        <div className="lens-row">
          <span className="rank-meta">{t("Split coverage by")}</span>
          <LensPicker lens={lens} onChange={setLens} available={available ?? undefined} />
        </div>
        <span className="feed-toolbar__now">
          {days === 1 ? t("Today") : tn(days, "{n} day", "{n} days")} · {sort === "top" ? t("Most covered") : t("Latest")}
        </span>
        <button type="button" className="btn btn--sm filters__toggle" aria-expanded={filtersOpen}
          aria-controls={ids.panel} onClick={() => setFiltersOpen((o) => !o)}>
          {t("Filter stories")}{activeFilters ? ` (${activeFilters})` : ""}
        </button>
        {/* the period and the order: on the line itself where there is room, with the filters on a phone */}
        <div className="feed-toolbar__more">
          <FilterBar presets={FEED_PRESETS} defaultDays={FEED_DEFAULT_DAYS} showSources={false} />
          <div className="segmented" role="group" aria-label={t("Order")}>
            <button type="button" aria-pressed={sort === "top"} onClick={() => set("sort", "")}>{t("Most covered")}</button>
            <button type="button" aria-pressed={sort === "latest"} onClick={() => set("sort", "latest")}>{t("Latest")}</button>
          </div>
        </div>
        <div id={ids.panel} className={`filters__panel ${filtersOpen ? "is-open" : ""}`}>
          <SourceSelect defaultDays={FEED_DEFAULT_DAYS} />
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

      <div className="front">
        {/* the lead first: on a phone the top story opens the page */}
        <section className={`front__lead ${refetching ?? ""}`} aria-labelledby="feed-heading">
          <h2 id="feed-heading" className="visually-hidden">
            {data ? tn(data.total, "{n} story", "{n} stories") : t("Stories")}
          </h2>
          {stories.isPending ? (
            <LoadingBlock height={480} label={t("Loading {title}", { title: t("Stories") })} />
          ) : stories.isError ? (
            <ErrorState error={stories.error} onRetry={() => void stories.refetch()} />
          ) : !items.length ? (
            <EmptyState>
              {q ? t("No story matches this search.") : t("No story was covered by two or more outlets in this period yet. Try a longer period.")}
            </EmptyState>
          ) : (
            <>
              {hero && <HeroStory story={hero} lens={lens} />}
              <div className="sec-head">
                <h2>{sort === "top" ? t("Most covered") : t("Latest")}</h2>
                <p>{tn(data!.total, "{n} story", "{n} stories")}</p>
              </div>
              <ol className="story-list story-list--top">
                {list.slice(0, TOP).map((s) => (
                  <li key={s.id}><StoryRow story={s} lens={lens} /></li>
                ))}
              </ol>
            </>
          )}
        </section>

        <aside className="front__rail" aria-label={t("Blindspot")}>
          <section className="card" aria-labelledby="blindspot-heading">
            <div className="card__head">
              <div>
                <h2 id="blindspot-heading">{t("Blindspot")}</h2>
                <p className="card__question">
                  {t("Stories one side — or one country's outlets — barely covered.")}{" "}
                  <Link to="/about#stories">{t("How blindspots work")}</Link>
                </p>
              </div>
            </div>
            {blind.isPending ? (
              <LoadingBlock height={240} />
            ) : blind.isError ? (
              <ErrorState error={blind.error} onRetry={() => void blind.refetch()} />
            ) : blind.data?.items.length ? (
              <div className="blindspot-list">
                {blind.data.items.slice(0, 3).map((s) => <BlindspotCard key={s.id} story={s} lens={blindLens} />)}
              </div>
            ) : (
              <EmptyState>{t("No blindspot in this period.")}</EmptyState>
            )}
            <Link className="more-link" to="/blindspot" aria-label={t("All blindspots")}>{t("View the blindspot feed")} →</Link>
          </section>
          <section className="card" aria-labelledby="mybias-heading">
            <div className="card__head">
              <div>
                <h2 id="mybias-heading">{t("My news bias")}</h2>
                <p className="card__question">{t("Which outlets you read here, by perspective and region.")}</p>
              </div>
            </div>
            <p className="rail-text">
              {readCount
                ? tn(readCount, "You opened {n} article recently.", "You opened {n} articles recently.")
                : t("Open articles from the stories to see the balance of your reading.")}{" "}
              {t("Stored only in this browser.")}
            </p>
            <Link className="more-link" to="/my-news">{t("See your balance")} →</Link>
          </section>
          {sort === "top" && (
            <section className="card card--bare" aria-labelledby="latest-heading">
              <div className="card__head"><h2 id="latest-heading">{t("Latest stories")}</h2></div>
              {latest.isPending ? (
                <LoadingBlock height={240} />
              ) : latest.isError ? (
                <ErrorState error={latest.error} onRetry={() => void latest.refetch()} />
              ) : (
                <div className="story-briefs">
                  {(latest.data?.items ?? []).slice(0, 5).map((s) => <StoryLine key={s.id} story={s} lens={latestLens} />)}
                </div>
              )}
            </section>
          )}
          {names.length > 0 && (
            <nav className="card card--bare" aria-labelledby="trending-heading">
              <div className="card__head"><h2 id="trending-heading">{t("Suddenly in the news")}</h2></div>
              <ul className="chips">
                {names.map((e) => (
                  <li key={e.id}><Link className="chip" to={`/entities/${e.id}`}>{e.name}</Link></li>
                ))}
              </ul>
            </nav>
          )}
        </aside>

        {list.length > TOP && (
          <section className={`front__more ${refetching ?? ""}`} aria-labelledby="more-heading">
            <div className="sec-head"><h2 id="more-heading">{t("More stories")}</h2></div>
            <ol className="story-list story-list--more">
              {list.slice(TOP).map((s) => (
                <li key={s.id}><StoryRow story={s} lens={lens} /></li>
              ))}
            </ol>
          </section>
        )}
        {data && data.pages > 1 && (
          <nav className="pagination front__pages" aria-label={t("Pagination")}>
            <button type="button" className="btn btn--sm" disabled={page <= 1}
              onClick={() => set("page", String(page - 1))}>← {t("Previous")}</button>
            <span aria-live="polite">{t("Page {page} of {pages}", { page: data.page, pages: data.pages })}</span>
            <button type="button" className="btn btn--sm" disabled={page >= data.pages || page >= 200}
              onClick={() => set("page", String(page + 1))}>{t("Next")} →</button>
          </nav>
        )}
      </div>
    </>
  );
}
