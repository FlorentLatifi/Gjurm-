import { useId } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { isNotFound } from "@/shared/api/client";
import { useTitle } from "@/shared/hooks/useTitle";
import {
  ENTITY_TYPE_LABEL,
  EVENT_TYPE_LABEL,
  formatDateTime,
  formatPercent,
  formatScore,
  hostOf,
  realSummary,
  safeHref,
} from "@/shared/lib/format";
import { recordRead } from "@/stores/reading";
import { Card } from "@/ui/Card";
import { SentimentChip } from "@/ui/SentimentChip";
import { SearchField } from "@/ui/SearchField";
import { ErrorState, LoadingBlock, NotFoundState } from "@/ui/States";
import { ArticleList } from "../ArticleList";
import { useApiQuery } from "@/shared/query/apiQuery";
import { articleQueries, articlesQueries, articlesState } from "../queries";
import { isPositiveId } from "@/shared/lib/ids";
import { localName, t, tn } from "@/shared/i18n";
import { countryLabel } from "@/shared/model/ratings";

export function ArticlesPage() {
  useTitle(t("Articles"), t("Search Albanian-language news by keyword, topic, outlet, tone and date."));
  const { filters } = useFilters();
  const [params, setParams] = useSearchParams();
  const queries = articlesQueries(params);
  const taxonomy = useApiQuery(queries.taxonomy);
  const ids = { q: useId(), topic: useId(), sentiment: useId(), sort: useId() };
  const { q, topic, sentiment, sort, entity, page } = articlesState(params);

  const set = (key: string, value: string) =>
    setParams((prev) => {
      const out = new URLSearchParams(prev);
      if (value) out.set(key, value);
      else out.delete(key);
      if (key !== "page") out.delete("page");
      return out;
    });


  const articles = useApiQuery(queries.articles);
  const data = articles.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("Articles")}</h1>
          <p>{t("Headlines link to the original publisher. Summaries, topics and tone are AI-generated.")}</p>
        </div>
      </div>
      <FilterBar />
      <form className="filters" role="search" onSubmit={(e) => e.preventDefault()}>
        <SearchField id={ids.q} label={t("Keyword in headline")} value={q} onCommit={(v) => set("q", v)}
          placeholder={t("e.g. zgjedhjet, Prizren, buxheti")} />
        <div className="field">
          <label htmlFor={ids.topic}>{t("Topic")}</label>
          <select id={ids.topic} value={topic} onChange={(e) => set("topic", e.target.value)}>
            <option value="">{t("Any topic")}</option>
            {taxonomy.data?.map((tp) => <option key={tp.slug} value={tp.slug}>{localName(tp.name_en, tp.name_sq)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor={ids.sentiment}>{t("Tone")}</label>
          <select id={ids.sentiment} value={sentiment} onChange={(e) => set("sentiment", e.target.value)}>
            <option value="">{t("Any tone")}</option>
            <option value="negative">{t("Negative")}</option>
            <option value="neutral">{t("Neutral")}</option>
            <option value="positive">{t("Positive")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={ids.sort}>{t("Sort")}</label>
          <select id={ids.sort} value={sort} onChange={(e) => set("sort", e.target.value === "oldest" ? "oldest" : "")}>
            <option value="newest">{t("Newest first")}</option>
            <option value="oldest">{t("Oldest first")}</option>
          </select>
        </div>
        {entity && (
          <button type="button" className="btn btn--sm" onClick={() => set("entity", "")}>
            {t("Clear name filter")} ✕
          </button>
        )}
      </form>
      <Card title={data ? tn(data.total, "{n} article", "{n} articles") : t("Articles")} query={articles}
        empty={!data?.items.length}
        emptyText={t("No articles match these filters. Try a longer time range or fewer filters.")}>
        {() => (
          <>
            <ArticleList items={data!.items} filters={filters} />
            <nav className="pagination" aria-label={t("Pagination")}>
              <button type="button" className="btn btn--sm" disabled={page <= 1}
                onClick={() => set("page", String(page - 1))}>← {t("Newer")}</button>
              <span aria-live="polite">{t("Page {page} of {pages}", { page: data!.page, pages: data!.pages })}</span>
              <button type="button" className="btn btn--sm" disabled={page >= data!.pages || page >= 500}
                onClick={() => set("page", String(page + 1))}>{t("Older")} →</button>
            </nav>
          </>
        )}
      </Card>
      <p className="card__foot">
        {t("Tip: filters are part of the URL — copy the address bar to share this exact view.")}{" "}
        <Link to={withFilters("/", filters)}>{t("Back to the stories")}</Link>
      </p>
    </>
  );
}

export function ArticlePage() {
  const id = Number(useParams().id);
  const valid = isPositiveId(id);
  const article = useApiQuery(articleQueries(id).article, valid);
  const a = article.data;
  const missing = !valid || isNotFound(article.error);
  useTitle(missing ? t("Article not found") : (a?.title ?? t("Article")), undefined, { index: !missing });
  if (missing) {
    return (
      <NotFoundState title={t("Article not found")}>
        {t("This article does not exist, or was removed at the publisher's or a person's request.")}
      </NotFoundState>
    );
  }
  if (article.isPending) return <LoadingBlock height={300} />;
  if (article.isError || !a) return <ErrorState error={article.error} />;
  const href = safeHref(a.url);

  return (
    <article className="stack article-page">
      <div>
        <p className="rank-meta"><Link to="/articles">{t("Articles")}</Link> /</p>
        <h1 lang={a.language}>{a.title}</h1>
        <p style={{ color: "var(--ink-2)", marginTop: 8 }}>
          <strong>{a.source_name}</strong> · <time dateTime={a.published_at}>{formatDateTime(a.published_at)}</time>
          {a.author && <> · {a.author}</>}
        </p>
        {href && (
          <p className="chips mt-3">
            <a className="btn" href={href} target="_blank" rel="noopener noreferrer"
              onClick={() => recordRead(a.source_slug, a.story_id, a.topic_slug)}>
              {t("Read the full article on {host}", { host: hostOf(a.url) })} ↗
            </a>
            {a.story_id && <Link className="btn" to={`/stories/${a.story_id}`}>{t("Compare how other outlets covered it")}</Link>}
          </p>
        )}
      </div>
      <section className="card" aria-labelledby="ai-heading">
        <h2 id="ai-heading">{a.analysis_method === "rules" ? t("Rule-based analysis") : t("AI analysis")}</h2>
        <p className="card__question">
          {a.analysis_method === "rules"
            ? t("Assigned by keyword rules, not by an AI model — treat topics, tone and names as rough.")
            : a.analysis_model
              ? t("Generated automatically by {model} — it can be wrong.", { model: a.analysis_model })
              : t("Generated automatically — it can be wrong.")}{" "}
          {t("Report errors via the Methodology page.")}
        </p>
        {a.enrichment_status !== "succeeded" ? (
          <p className="mt-3">{t("This article has not been analysed yet ({status}).", { status: a.enrichment_status })}</p>
        ) : (
          <dl className="facts mt-3">
            <dt>{t("Summary")}</dt><dd>{realSummary(a.summary_en)
              ? <span lang="en">{realSummary(a.summary_en)}</span>
              : <span className="meta">{t("None — keyword rules do not write summaries.")}</span>}</dd>
            <dt>{t("Topics")}</dt>
            <dd className="chips">
              {a.topics.map((tp) => (
                <Link key={tp.slug} className="chip" to={`/topics/${tp.slug}`}>{localName(tp.name_en, tp.name_sq)}{tp.is_primary ? ` ${t("(main)")}` : ""}</Link>
              ))}
            </dd>
            <dt>{t("Tone")}</dt><dd><SentimentChip label={a.sentiment_label} /> {formatScore(a.sentiment_score)}</dd>
            <dt>{t("Event type")}</dt><dd>{EVENT_TYPE_LABEL[a.event_type ?? "other"] ?? a.event_type}</dd>
            <dt>{t("Mentions")}</dt>
            <dd className="chips">
              {a.entities.length ? a.entities.map((e) => (
                <Link key={e.id} className="chip" to={`/entities/${e.id}`}>{e.name} · {ENTITY_TYPE_LABEL[e.type]}</Link>
              )) : "—"}
            </dd>
            <dt>{t("Countries")}</dt><dd>{a.countries.map(countryLabel).join(", ") || "—"}</dd>
            <dt>{t("Confidence")}</dt>
            <dd>
              {formatPercent(a.enrichment_confidence)}{" "}
              {a.analysis_method === "rules" ? t("(fixed value of the keyword rules)") : t("(model self-assessment)")}
            </dd>
          </dl>
        )}
      </section>
      {a.related.length > 0 && (
        <section className="card" aria-labelledby="related-heading">
          <h2 id="related-heading">{t("Same story elsewhere")}</h2>
          <ul className="bullets mt-3">
            {a.related.map((r) => (
              <li key={r.id}>
                {safeHref(r.url) ? <a href={safeHref(r.url)} target="_blank" rel="noopener noreferrer"
                  onClick={() => recordRead(r.source_slug, a.story_id, a.topic_slug)}>{r.title}</a> : r.title}
                <span className="rank-meta"> · {r.source_name} · {formatDateTime(r.published_at)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
