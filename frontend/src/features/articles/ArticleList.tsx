import { Link } from "react-router-dom";

import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import type { ArticleSummary } from "@/shared/api/types";
import { formatDateTime, hostOf, safeHref } from "@/shared/lib/format";
import { recordRead } from "@/stores/reading";
import { SentimentChip } from "@/ui/SentimentChip";

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
                lang={a.language} onClick={() => recordRead(a.source_slug, a.story_id, a.topic_slug)}>
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
              {a.story_id ? (
                <Link className="chip" to={`/stories/${a.story_id}`} aria-label={`All coverage of: ${a.title}`}>
                  Full coverage
                </Link>
              ) : (
                a.duplicate_of_id && <span className="chip" title="Near-identical headline published by another outlet">Also reported elsewhere</span>
              )}
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
