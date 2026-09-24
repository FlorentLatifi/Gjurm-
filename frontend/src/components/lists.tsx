import { Link } from "react-router-dom";

import type { ArticleSummary, SentimentLabel } from "../api/types";
import { useFilters, withFilters } from "../lib/filters";
import { formatDateTime, formatInt, hostOf, safeHref } from "../lib/format";

const SENTIMENT_COLOR: Record<SentimentLabel, string> = {
  negative: "var(--sent-negative)",
  neutral: "var(--sent-neutral)",
  positive: "var(--sent-positive)",
};

export function SentimentChip({ label }: { label: SentimentLabel | null }) {
  if (!label) return null;
  return (
    <span className="chip">
      <span className="dot" style={{ background: SENTIMENT_COLOR[label] }} aria-hidden="true" />
      <span>{label[0]!.toUpperCase() + label.slice(1)} tone</span>
    </span>
  );
}

/**
 * Article rows: the headline links to the ORIGINAL publisher page (never republished here),
 * with the source named next to it; the English summary is our own AI-generated text.
 */
export function ArticleList({ items }: { items: ArticleSummary[] }) {
  const { filters } = useFilters();
  return (
    <ol className="articles">
      {items.map((a) => {
        const href = safeHref(a.url);
        return (
          <li key={a.id} className="article">
            {href ? (
              <a className="article__title" href={href} target="_blank" rel="noopener noreferrer"
                lang={a.language}>
                {a.title}
                <span className="visually-hidden"> (opens {hostOf(a.url)} in a new tab)</span>
              </a>
            ) : (
              <span className="article__title" lang={a.language}>{a.title}</span>
            )}
            {a.summary_en && <p className="article__summary">{a.summary_en}</p>}
            <div className="article__meta">
              <span>
                <strong style={{ color: "var(--ink-2)" }}>{a.source_name}</strong> ·{" "}
                <time dateTime={a.published_at}>{formatDateTime(a.published_at)}</time>
                {a.published_at_estimated && <span title="The feed gave no usable date; time first seen"> (est.)</span>}
              </span>
              {a.topic_slug && (
                <Link className="chip" to={withFilters(`/topics/${a.topic_slug}`, filters)}>
                  {a.topic_name}
                </Link>
              )}
              <SentimentChip label={a.sentiment_label} />
              {a.duplicate_of_id && <span className="chip" title="Near-identical headline published by another outlet">Also reported elsewhere</span>}
              <Link to={`/articles/${a.id}`} className="chip" aria-label={`Analysis details for: ${a.title}`}>
                Details
              </Link>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export interface RankItem {
  key: string | number;
  label: string;
  href?: string;
  value: number;
  meta?: React.ReactNode;
  sublabel?: string;
}

/** Ranked horizontal bars as plain HTML: accessible by default, one hue (magnitude, not identity). */
export function RankList({ items, unit }: { items: RankItem[]; unit: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ol className="rank-list">
      {items.map((it) => (
        <li key={it.key} className="rank-row">
          <span>
            {it.href ? <Link to={it.href}>{it.label}</Link> : <span>{it.label}</span>}
            {it.sublabel && <span className="rank-meta"> · {it.sublabel}</span>}
          </span>
          <span className="rank-meta">
            {formatInt(it.value)} {unit}
            {it.meta}
          </span>
          <span className="rank-bar" style={{ width: `${(it.value / max) * 100}%` }} aria-hidden="true" />
        </li>
      ))}
    </ol>
  );
}
