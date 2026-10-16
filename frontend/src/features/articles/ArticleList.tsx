import { Link } from "react-router-dom";

import { type Filters, withFilters } from "@/shared/hooks/useFilters";
import type { ArticleSummary } from "@/shared/api/types";
import { formatDateTime, hostOf, realSummary, safeHref } from "@/shared/lib/format";
import { recordRead } from "@/stores/reading";
import { SentimentChip } from "@/ui/SentimentChip";
import "./articles.css";
import { localName, t } from "@/shared/i18n";

/**
 * Article rows: the headline links to the ORIGINAL publisher page (never republished here),
 * with the source named next to it; the English summary is our own AI-generated text. Topic links
 * carry the page's filters, which the page passes in (no URL subscription down here).
 */
export function ArticleList({ items, filters }: { items: ArticleSummary[]; filters: Filters }) {
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
                <span className="visually-hidden"> {t("(opens {host} in a new tab)", { host: hostOf(a.url) })}</span>
              </a>
            ) : (
              <span className="article__title" lang={a.language}>{a.title}</span>
            )}
            {realSummary(a.summary_en) && <p className="article__summary" lang="en">{realSummary(a.summary_en)}</p>}
            <div className="article__meta">
              <span>
                <strong>{a.source_name}</strong> ·{" "}
                <time dateTime={a.published_at}>{formatDateTime(a.published_at)}</time>
                {a.published_at_estimated && <span title={t("The feed gave no usable date; time first seen")}> {t("(est.)")}</span>}
              </span>
              {a.topic_slug && (
                <Link className="chip" to={withFilters(`/topics/${a.topic_slug}`, filters)}>
                  {localName(a.topic_name, a.topic_name_sq)}
                </Link>
              )}
              <SentimentChip label={a.sentiment_label} />
              {a.story_id ? (
                <Link className="chip" to={`/stories/${a.story_id}`} aria-label={t("All coverage of: {title}", { title: a.title })}>
                  {t("Full coverage")}
                </Link>
              ) : (
                a.duplicate_of_id && <span className="chip" title={t("Near-identical headline published by another outlet")}>{t("Also reported elsewhere")}</span>
              )}
              <Link to={`/articles/${a.id}`} className="chip" aria-label={t("Analysis details for: {title}", { title: a.title })}>
                {t("Details")}
              </Link>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
