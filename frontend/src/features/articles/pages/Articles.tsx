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
  formatInt,
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

export function ArticlesPage() {
  useTitle("Articles", "Search Albanian-language news by keyword, topic, outlet, tone and date.");
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
          <h1>Articles</h1>
          <p>Headlines link to the original publisher. Summaries, topics and tone are AI-generated.</p>
        </div>
      </div>
      <FilterBar />
      <form className="filters" role="search" onSubmit={(e) => e.preventDefault()}>
        <SearchField id={ids.q} label="Keyword in headline" value={q} onCommit={(v) => set("q", v)}
          placeholder="e.g. zgjedhjet, Prizren, buxheti" />
        <div className="field">
          <label htmlFor={ids.topic}>Topic</label>
          <select id={ids.topic} value={topic} onChange={(e) => set("topic", e.target.value)}>
            <option value="">Any topic</option>
            {taxonomy.data?.map((t) => <option key={t.slug} value={t.slug}>{t.name_en}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor={ids.sentiment}>Tone</label>
          <select id={ids.sentiment} value={sentiment} onChange={(e) => set("sentiment", e.target.value)}>
            <option value="">Any tone</option>
            <option value="negative">Negative</option>
            <option value="neutral">Neutral</option>
            <option value="positive">Positive</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={ids.sort}>Sort</label>
          <select id={ids.sort} value={sort} onChange={(e) => set("sort", e.target.value === "oldest" ? "oldest" : "")}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
        </div>
        {entity && (
          <button type="button" className="btn btn--sm" onClick={() => set("entity", "")}>
            Clear entity filter ✕
          </button>
        )}
      </form>
      <Card title={data ? `${formatInt(data.total)} articles` : "Articles"} query={articles}
        empty={!data?.items.length}
        emptyText="No articles match these filters. Try a longer time range or fewer filters.">
        {() => (
          <>
            <ArticleList items={data!.items} filters={filters} />
            <nav className="pagination" aria-label="Pagination">
              <button type="button" className="btn btn--sm" disabled={page <= 1}
                onClick={() => set("page", String(page - 1))}>← Newer</button>
              <span aria-live="polite">Page {data!.page} of {data!.pages}</span>
              <button type="button" className="btn btn--sm" disabled={page >= data!.pages || page >= 500}
                onClick={() => set("page", String(page + 1))}>Older →</button>
            </nav>
          </>
        )}
      </Card>
      <p className="card__foot">
        Tip: filters are part of the URL — copy the address bar to share this exact view.{" "}
        <Link to={withFilters("/", filters)}>Back to overview</Link>
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
  useTitle(missing ? "Article not found" : (a?.title ?? "Article"), undefined, { index: !missing });
  if (missing) {
    return (
      <NotFoundState title="Article not found">
        This article does not exist, or was removed at the publisher&apos;s or a person&apos;s request.
      </NotFoundState>
    );
  }
  if (article.isPending) return <LoadingBlock height={300} />;
  if (article.isError || !a) return <ErrorState error={article.error} />;
  const href = safeHref(a.url);

  return (
    <article className="stack article-page">
      <div>
        <p className="rank-meta"><Link to="/articles">Articles</Link> /</p>
        <h1 lang={a.language}>{a.title}</h1>
        <p style={{ color: "var(--ink-2)", marginTop: 8 }}>
          <strong>{a.source_name}</strong> · <time dateTime={a.published_at}>{formatDateTime(a.published_at)}</time>
          {a.author && <> · {a.author}</>}
        </p>
        {href && (
          <p className="chips mt-3">
            <a className="btn" href={href} target="_blank" rel="noopener noreferrer"
              onClick={() => recordRead(a.source_slug, a.story_id, a.topic_slug)}>
              Read the full article on {hostOf(a.url)} ↗
            </a>
            {a.story_id && <Link className="btn" to={`/stories/${a.story_id}`}>Compare how other outlets covered it</Link>}
          </p>
        )}
      </div>
      <section className="card" aria-labelledby="ai-heading">
        <h2 id="ai-heading">{a.analysis_method === "rules" ? "Rule-based analysis" : "AI analysis"}</h2>
        <p className="card__question">
          {a.analysis_method === "rules"
            ? "Assigned by keyword rules, not by an AI model — treat topics, tone and names as rough."
            : `Generated automatically${a.analysis_model ? ` by ${a.analysis_model}` : ""} — it can be wrong.`}{" "}
          Report errors via the Methodology page.
        </p>
        {a.enrichment_status !== "succeeded" ? (
          <p className="mt-3">This article has not been analysed yet ({a.enrichment_status}).</p>
        ) : (
          <dl className="facts mt-3">
            <dt>Summary</dt><dd>{realSummary(a.summary_en) ?? <span className="meta">None — keyword rules do not write summaries.</span>}</dd>
            <dt>Topics</dt>
            <dd className="chips">
              {a.topics.map((t) => (
                <Link key={t.slug} className="chip" to={`/topics/${t.slug}`}>{t.name_en}{t.is_primary ? " (main)" : ""}</Link>
              ))}
            </dd>
            <dt>Tone</dt><dd><SentimentChip label={a.sentiment_label} /> {formatScore(a.sentiment_score)}</dd>
            <dt>Event type</dt><dd>{EVENT_TYPE_LABEL[a.event_type ?? "other"] ?? a.event_type}</dd>
            <dt>Mentions</dt>
            <dd className="chips">
              {a.entities.length ? a.entities.map((e) => (
                <Link key={e.id} className="chip" to={`/entities/${e.id}`}>{e.name} · {ENTITY_TYPE_LABEL[e.type]}</Link>
              )) : "—"}
            </dd>
            <dt>Countries</dt><dd>{a.countries.join(", ") || "—"}</dd>
            <dt>Confidence</dt>
            <dd>
              {formatPercent(a.enrichment_confidence)}{" "}
              {a.analysis_method === "rules" ? "(fixed value of the keyword rules)" : "(model self-assessment)"}
            </dd>
          </dl>
        )}
      </section>
      {a.related.length > 0 && (
        <section className="card" aria-labelledby="related-heading">
          <h2 id="related-heading">Same story elsewhere</h2>
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
