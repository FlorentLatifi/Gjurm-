import { useEffect, useId, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useArticle, useArticles, useTaxonomy } from "../api/hooks";
import { Card } from "../components/Card";
import { FilterBar } from "../components/FilterBar";
import { ArticleList, SentimentChip } from "../components/lists";
import { ErrorState, LoadingBlock } from "../components/States";
import { useFilters, withFilters } from "../lib/filters";
import {
  ENTITY_TYPE_LABEL,
  EVENT_TYPE_LABEL,
  formatDateTime,
  formatInt,
  formatPercent,
  formatScore,
  hostOf,
  safeHref,
} from "../lib/format";
import { useTitle } from "../lib/useTitle";

export function ArticlesPage() {
  useTitle("Articles", "Search Albanian-language news by keyword, topic, outlet, tone and date.");
  const { filters, apiParams } = useFilters();
  const [params, setParams] = useSearchParams();
  const taxonomy = useTaxonomy();
  const [text, setText] = useState(params.get("q") ?? "");
  const ids = { q: useId(), topic: useId(), sentiment: useId(), sort: useId() };

  const q = params.get("q") ?? "";
  const topic = params.get("topic") ?? "";
  const sentiment = params.get("sentiment") ?? "";
  const sort = params.get("sort") === "oldest" ? "oldest" : "newest";
  const entity = params.get("entity") ?? "";
  const page = Math.max(1, Number(params.get("page")) || 1);

  const set = (key: string, value: string) =>
    setParams((prev) => {
      const out = new URLSearchParams(prev);
      if (value) out.set(key, value);
      else out.delete(key);
      if (key !== "page") out.delete("page");
      return out;
    });

  useEffect(() => {
    const id = setTimeout(() => {
      const v = text.trim();
      if (v !== q && (v.length >= 2 || v.length === 0)) set("q", v);
    }, 350);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const articles = useArticles({
    ...apiParams, q: q || undefined, topic: topic || undefined, sentiment: sentiment || undefined,
    entity: entity || undefined, sort, page, page_size: 20,
  });
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
      <form className="filters" role="search" onSubmit={(e) => { e.preventDefault(); set("q", text.trim()); }}>
        <div className="field field--grow">
          <label htmlFor={ids.q}>Keyword in headline</label>
          <input id={ids.q} type="search" value={text} onChange={(e) => setText(e.target.value)}
            placeholder="e.g. zgjedhjet, Prizren, buxheti" maxLength={120} />
        </div>
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
            <ArticleList items={data!.items} />
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
      <p className="card__foot" style={{ marginTop: 10 }}>
        Tip: filters are part of the URL — copy the address bar to share this exact view.{" "}
        <Link to={withFilters("/", filters)}>Back to overview</Link>
      </p>
    </>
  );
}

export function ArticlePage() {
  const id = Number(useParams().id);
  const article = useArticle(id);
  const a = article.data;
  useTitle(a?.title ?? "Article");
  if (article.isPending) return <LoadingBlock height={300} />;
  if (article.isError || !a) return <ErrorState error={article.error} />;
  const href = safeHref(a.url);

  return (
    <article className="stack" style={{ maxWidth: 860 }}>
      <div>
        <p className="rank-meta"><Link to="/articles">Articles</Link> /</p>
        <h1 lang={a.language} style={{ marginTop: 4 }}>{a.title}</h1>
        <p style={{ color: "var(--ink-2)", marginTop: 8 }}>
          <strong>{a.source_name}</strong> · <time dateTime={a.published_at}>{formatDateTime(a.published_at)}</time>
          {a.author && <> · {a.author}</>}
        </p>
        {href && (
          <p style={{ marginTop: 12 }}>
            <a className="btn" href={href} target="_blank" rel="noopener noreferrer">
              Read the full article on {hostOf(a.url)} ↗
            </a>
          </p>
        )}
      </div>
      <section className="card" aria-labelledby="ai-heading">
        <h2 id="ai-heading">AI analysis</h2>
        <p className="card__question">Generated automatically — it can be wrong. Report errors via the Methodology page.</p>
        {a.enrichment_status !== "succeeded" ? (
          <p style={{ marginTop: 10 }}>This article has not been analysed yet ({a.enrichment_status}).</p>
        ) : (
          <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "8px 16px", margin: "12px 0 0" }}>
            <dt>Summary</dt><dd style={{ margin: 0 }}>{a.summary_en}</dd>
            <dt>Topics</dt>
            <dd style={{ margin: 0, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {a.topics.map((t) => (
                <Link key={t.slug} className="chip" to={`/topics/${t.slug}`}>{t.name_en}{t.is_primary ? " (main)" : ""}</Link>
              ))}
            </dd>
            <dt>Tone</dt><dd style={{ margin: 0 }}><SentimentChip label={a.sentiment_label} /> {formatScore(a.sentiment_score)}</dd>
            <dt>Event type</dt><dd style={{ margin: 0 }}>{EVENT_TYPE_LABEL[a.event_type ?? "other"] ?? a.event_type}</dd>
            <dt>Mentions</dt>
            <dd style={{ margin: 0, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {a.entities.length ? a.entities.map((e) => (
                <Link key={e.id} className="chip" to={`/entities/${e.id}`}>{e.name} · {ENTITY_TYPE_LABEL[e.type]}</Link>
              )) : "—"}
            </dd>
            <dt>Countries</dt><dd style={{ margin: 0 }}>{a.countries.join(", ") || "—"}</dd>
            <dt>Confidence</dt><dd style={{ margin: 0 }}>{formatPercent(a.enrichment_confidence)} (model self-assessment)</dd>
          </dl>
        )}
      </section>
      {a.related.length > 0 && (
        <section className="card" aria-labelledby="related-heading">
          <h2 id="related-heading">Same story elsewhere</h2>
          <ul style={{ margin: "10px 0 0", paddingLeft: 18, display: "grid", gap: 6 }}>
            {a.related.map((r) => (
              <li key={r.id}>
                {safeHref(r.url) ? <a href={safeHref(r.url)} target="_blank" rel="noopener noreferrer">{r.title}</a> : r.title}
                <span className="rank-meta"> · {r.source_name} · {formatDateTime(r.published_at)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
