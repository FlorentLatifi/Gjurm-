import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import { useTitle } from "@/shared/hooks/useTitle";
import { useApiQuery } from "@/shared/query/apiQuery";
import { summaryFor } from "@/shared/lib/format";
import { availableLenses, countryLabel, REGION_ORDER } from "@/shared/model/ratings";
import { useReadingCount } from "@/stores/reading";
import { Card } from "@/ui/Card";
import { SearchField } from "@/ui/SearchField";
import { EmptyState, ErrorState, LoadingBlock } from "@/ui/States";

import { BlindspotCard, Cover, HeroStory, loadStoryPage, StoryLine, StoryRow } from "../StoryCard";
import { LensPicker } from "../StoryCoverage";
import { useLens } from "../useLens";
import { FEED_DEFAULT_DAYS, feedQueries, feedState } from "../queries";
import { localName, t, tn } from "@/shared/i18n";

export const FEED_PRESETS = [1, 3, 7, 30] as const;

/**
 * The home page, laid out as Ground News' front page: the lead story large in the middle column
 * with the rest of the feed under it, the daily briefing and the latest stories on the left, the
 * blindspots and the reader's own bias on the right. Every story shows how its coverage splits.
 */
export default function StoriesPage() {
  useTitle("", t("Albanian and Balkan news grouped into stories, with how each outlet covered them."));
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
  const latest = useApiQuery(queries.latest);
  const blind = useApiQuery(queries.blindspots);
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
  const briefing = hero ?? items[0];
  const activeFilters = [topic, country, q].filter(Boolean).length;

  return (
    <>
      <h1 className="visually-hidden">{t("Top stories")}</h1>
      <div className="feed-toolbar" role="group" aria-label={t("Story filters")}>
        <FilterBar presets={FEED_PRESETS} defaultDays={FEED_DEFAULT_DAYS} />
        <div className="segmented" role="group" aria-label={t("Order")}>
          <button type="button" aria-pressed={sort === "top"} onClick={() => set("sort", "")}>{t("Most covered")}</button>
          <button type="button" aria-pressed={sort === "latest"} onClick={() => set("sort", "latest")}>{t("Latest")}</button>
        </div>
        <div className="lens-row">
          <span className="rank-meta">{t("Split coverage by")}</span>
          <LensPicker lens={lens} onChange={setLens} available={available ?? undefined} />
        </div>
        <button type="button" className="btn btn--sm filters__toggle" aria-expanded={filtersOpen}
          aria-controls={ids.panel} onClick={() => setFiltersOpen((o) => !o)}>
          {t("Filter stories")}{activeFilters ? ` (${activeFilters})` : ""}
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

      <div className="front">
        {/* the middle column first: on a phone the lead story opens the page */}
        <section className="front__main" aria-labelledby="feed-heading">
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
            <div className={stories.isPlaceholderData && stories.isFetching ? "card--refetching" : undefined}>
              {hero && <HeroStory story={hero} lens={lens} />}
              <ol className="story-list">
                {rest.filter((s) => s !== undefined).map((s) => (
                  <li key={s.id}><StoryRow story={s} lens={lens} /></li>
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
            </div>
          )}
        </section>

        <aside className="front__left" aria-label={t("Daily briefing and latest stories")}>
          {briefing && (
            <section className="briefing" aria-labelledby="briefing-heading">
              <h2 id="briefing-heading" className="front__heading">{t("Daily briefing")}</h2>
              <Link className="briefing__card" to={`/stories/${briefing.id}`}>
                <Cover story={briefing} className="briefing__cover" />
                <span className="briefing__body">
                  <span className="briefing__meta">
                    {tn(briefing.source_count, "{n} outlet", "{n} outlets")} · {tn(briefing.article_count, "{n} article", "{n} articles")}
                  </span>
                  <span className="briefing__title" lang={briefing.language}>{briefing.title}</span>
                  {summaryFor(briefing) && (
                    <span className="briefing__summary" lang={summaryFor(briefing)!.lang}>{summaryFor(briefing)!.text}</span>
                  )}
                </span>
              </Link>
            </section>
          )}
          <section aria-labelledby="latest-heading">
            <h2 id="latest-heading" className="front__heading">{t("Latest stories")}</h2>
            {latest.isPending ? (
              <LoadingBlock height={240} />
            ) : latest.isError ? (
              <ErrorState error={latest.error} onRetry={() => void latest.refetch()} />
            ) : (
              <div className="story-lines">
                {(latest.data?.items ?? []).map((s) => <StoryLine key={s.id} story={s} lens={latestLens} />)}
              </div>
            )}
          </section>
        </aside>

        <aside className="front__right" aria-label={t("Blindspot")}>
          <section className="blindspot-box" aria-labelledby="blindspot-heading">
            <h2 id="blindspot-heading" className="blindspot-mark">
              <svg viewBox="0 0 48 28" aria-hidden="true">
                <circle cx="14" cy="14" r="11" fill="none" stroke="currentColor" strokeWidth="4" />
                <circle cx="34" cy="14" r="11" fill="none" stroke="currentColor" strokeWidth="4" />
                <path d="M14 9h20M14 19h20" stroke="currentColor" strokeWidth="4" />
              </svg>
              {t("Blindspot")}
            </h2>
            <p className="blindspot-box__intro">
              {t("Stories one side — or one country's outlets — barely covered.")}{" "}
              <Link to="/about#stories">{t("How blindspots work")}</Link>
            </p>
            {blind.isPending ? (
              <LoadingBlock height={240} />
            ) : blind.isError ? (
              <ErrorState error={blind.error} onRetry={() => void blind.refetch()} />
            ) : blind.data?.items.length ? (
              <div className="stack">
                {blind.data.items.slice(0, 3).map((s) => <BlindspotCard key={s.id} story={s} lens={blindLens} />)}
              </div>
            ) : (
              <EmptyState>{t("No blindspot in this period.")}</EmptyState>
            )}
            <Link className="btn btn--block" to="/blindspot" aria-label={t("All blindspots")}>{t("View the blindspot feed")}</Link>
          </section>
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
        </aside>
      </div>
    </>
  );
}
