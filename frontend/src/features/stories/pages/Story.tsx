import { Link, useParams } from "react-router-dom";

import type { StoryArticle, StoryDetail } from "@/shared/api/types";
import { useTitle } from "@/shared/hooks/useTitle";
import { useApiQuery } from "@/shared/query/apiQuery";
import { ENTITY_TYPE_LABEL, formatDateTime, formatRelative, hostOf, safeHref } from "@/shared/lib/format";
import {
  BIAS_GROUP_COLOR,
  BIAS_LABEL,
  biasGroup,
  countryLabel,
  FACTUALITY_LABEL,
  type Lens,
  LENS_LABEL,
  noneRated,
  OWNERSHIP_LABEL,
  REGION_ORDER,
  segments,
} from "@/shared/model/ratings";
import { recordRead } from "@/stores/reading";
import { Card } from "@/ui/Card";
import { SentimentChip } from "@/ui/SentimentChip";
import { ErrorState, LoadingBlock } from "@/ui/States";
import { BlindspotBadges, StoryCard } from "../StoryCard";
import { LensPicker, StoryCoverage } from "../StoryCoverage";
import { useLens } from "../useLens";
import { storyQueries } from "../queries";
import { isPositiveId } from "@/shared/lib/ids";

function groupOf(a: StoryArticle, lens: Lens): string {
  if (lens === "perspective") return biasGroup(a.source_bias);
  if (lens === "region") return REGION_ORDER.includes(a.source_country) ? a.source_country : "other";
  if (lens === "ownership") return a.source_ownership;
  const f = a.source_factuality;
  return f === "very_high" || f === "high" ? "high" : f === "very_low" || f === "low" ? "low" : f;
}

function OutletLink({ story, a }: { story: StoryDetail; a: StoryArticle }) {
  const href = safeHref(a.url);
  if (!href) return <span lang={a.language}>{a.title}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" lang={a.language}
      onClick={() => recordRead(a.source_slug, story.id, story.topic_slug)}>
      {a.title}
      <span className="visually-hidden"> (opens {hostOf(a.url)} in a new tab)</span>
    </a>
  );
}

/** Every outlet's headline side by side, grouped by the chosen lens (Ground News' "compare"). */
function HeadlineColumns({ story, lens }: { story: StoryDetail; lens: Lens }) {
  const columns = segments(story.coverage, lens)
    .map((seg) => ({ seg, articles: story.articles.filter((a) => groupOf(a, lens) === seg.key) }))
    .filter((c) => c.articles.length);
  return (
    <div className="headline-columns">
      {columns.map(({ seg, articles }) => (
        <section key={seg.key} className="headline-column" aria-label={`${seg.label}: ${articles.length} articles`}
          style={{ ["--col-color" as string]: seg.color }}>
          <h3>{seg.label} · {articles.length}</h3>
          {articles.map((a) => (
            <div key={a.id} className="headline">
              <OutletLink story={story} a={a} />
              <span className="headline__meta">
                <Link to={`/sources/${a.source_slug}`}>{a.source_name}</Link> · {formatDateTime(a.published_at)}
                {a.is_first && <> · <strong>first report</strong></>}
              </span>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

export function StoryPage() {
  const id = Number(useParams().id);
  const query = useApiQuery(storyQueries(id).story, isPositiveId(id));
  const s = query.data;
  useTitle(s?.title ?? "Story", s ? `${s.source_count} outlets covered this story.` : undefined);
  const [lens, setLens] = useLens(s ? noneRated([s.coverage]) : false);
  if (query.isPending) return <LoadingBlock height={320} />;
  if (query.isError || !s) return <ErrorState error={query.error} />;
  const first = s.articles.find((a) => a.is_first) ?? s.articles[0]!;
  const summary = s.summary_en && !s.summary_en.startsWith("[headline") ? s.summary_en : null;

  return (
    <article className="stack">
      <div>
        <p className="rank-meta">
          <Link to="/">Stories</Link> /{" "}
          {s.topic_slug ? <Link to={`/topics/${s.topic_slug}`}>{s.topic_name}</Link> : "Story"}
        </p>
        <h1 lang={s.language} style={{ marginTop: 4, maxWidth: "40ch" }}>{s.title}</h1>
        <p style={{ color: "var(--ink-2)", marginTop: 8, display: "flex", flexWrap: "wrap", gap: "4px 12px", alignItems: "center" }}>
          <span><strong>{s.source_count} {s.source_count === 1 ? "outlet" : "outlets"}</strong> · {s.article_count} articles</span>
          <span>First reported by <Link to={`/sources/${first.source_slug}`}>{first.source_name}</Link>, {formatDateTime(first.published_at)}</span>
          <span>Updated {formatRelative(s.last_published_at)}</span>
          <BlindspotBadges story={s} />
        </p>
        {summary && <p style={{ marginTop: 10, maxWidth: "75ch" }}>{summary} <span className="rank-meta">(AI summary)</span></p>}
      </div>

      <div className="feed-layout">
        <div className="stack">
          <Card title="How each outlet headlined it"
            question="Every outlet's own headline, linked to the original. Compare the wording."
            actions={<LensPicker lens={lens} onChange={setLens} />}>
            {() => <HeadlineColumns story={s} lens={lens} />}
          </Card>
          <Card title="Timeline" question="Who reported it, and when.">
            {() => (
              <ol className="timeline">
                {s.articles.map((a) => (
                  <li key={a.id} style={{ ["--dot-bias" as string]: BIAS_GROUP_COLOR[biasGroup(a.source_bias)] }}>
                    <time dateTime={a.published_at}>{formatDateTime(a.published_at)}</time>{" "}
                    <strong>{a.source_name}</strong>
                    {a.is_first && <span className="rank-meta"> · first</span>}
                    <div><OutletLink story={s} a={a} /> <SentimentChip label={a.sentiment_label} /></div>
                  </li>
                ))}
              </ol>
            )}
          </Card>
          {s.related.length > 0 && (
            <Card title="Related stories" question="Stories within three days that name the same people, organisations or places.">
              {() => <div>{s.related.map((r) => <StoryCard key={r.id} story={r} lens={lens} compact />)}</div>}
            </Card>
          )}
        </div>

        <aside className="feed-aside" aria-label="Coverage details">
          <Card title="Coverage details" question="Distinct outlets that covered this story.">
            {() => (
              <div className="stack" style={{ gap: 16 }}>
                {(["perspective", "factuality", "ownership", "region"] as Lens[]).map((l) => (
                  <div key={l} className="stack" style={{ gap: 6 }}>
                    <h3>{LENS_LABEL[l]}</h3>
                    <StoryCoverage coverage={s.coverage} lens={l} />
                  </div>
                ))}
                <dl className="facts">
                  <dt>Outlets</dt><dd>{s.source_count}</dd>
                  <dt>Articles</dt><dd>{s.article_count}</dd>
                  <dt>Tone</dt><dd>{s.tone.negative} negative · {s.tone.neutral} neutral · {s.tone.positive} positive</dd>
                  <dt>Started</dt><dd>{formatDateTime(s.first_published_at)}</dd>
                  <dt>Last update</dt><dd>{formatDateTime(s.last_published_at)}</dd>
                </dl>
                <p className="card__foot">
                  Ratings are editorial and belong to the outlet, not to the article.{" "}
                  <Link to="/about#ratings">How outlets are rated</Link>
                </p>
              </div>
            )}
          </Card>
          <Card title="Outlets" question="Their ratings, and where they are based.">
            {() => (
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
                {s.sources.map((src) => {
                  const a = s.articles.find((x) => x.source_slug === src.slug)!;
                  return (
                    <li key={src.slug} className="rating">
                      <span className="dot" style={{ background: BIAS_GROUP_COLOR[biasGroup(src.bias)] }} aria-hidden="true" />
                      <span>
                        <Link to={`/sources/${src.slug}`}>{src.name}</Link>
                        <span className="rank-meta" style={{ whiteSpace: "normal" }}> · {BIAS_LABEL[src.bias]} · {FACTUALITY_LABEL[a.source_factuality]} factuality · {OWNERSHIP_LABEL[a.source_ownership]} · {countryLabel(src.country)}</span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
          {(s.entities.length > 0 || s.topics.length > 0) && (
            <Card title="Tags" question="Topics and names in this story.">
              {() => (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {s.topics.map((t) => <Link key={t.slug} className="chip" to={`/topics/${t.slug}`}>{t.name_en}</Link>)}
                  {s.entities.map((e) => (
                    <Link key={e.id} className="chip" to={`/entities/${e.id}`}>{e.name} · {ENTITY_TYPE_LABEL[e.type]}</Link>
                  ))}
                </div>
              )}
            </Card>
          )}
        </aside>
      </div>
    </article>
  );
}
