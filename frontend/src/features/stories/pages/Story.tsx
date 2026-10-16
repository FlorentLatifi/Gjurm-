import { Link, useParams } from "react-router-dom";

import { isNotFound } from "@/shared/api/client";
import type { StoryArticle, StoryDetail } from "@/shared/api/types";
import { useTitle } from "@/shared/hooks/useTitle";
import { useApiQuery } from "@/shared/query/apiQuery";
import { ENTITY_TYPE_LABEL, formatDateTime, formatRelative, hostOf, safeHref, summaryFor } from "@/shared/lib/format";
import {
  BIAS_GROUP_COLOR,
  BIAS_LABEL,
  biasGroup,
  countryLabel,
  FACTUALITY_LABEL,
  type Lens,
  LENS_LABEL,
  availableLenses,
  OWNERSHIP_LABEL,
  segments,
} from "@/shared/model/ratings";
import { recordRead } from "@/stores/reading";
import { Card } from "@/ui/Card";
import { SentimentChip } from "@/ui/SentimentChip";
import { ErrorState, LoadingBlock, NotFoundState } from "@/ui/States";
import { BlindspotBadges, StoryCard } from "../StoryCard";
import { LensPicker, StoryCoverage } from "../StoryCoverage";
import { ShareStory } from "../ShareStory";
import { useLens } from "../useLens";
import { groupOf, markColor, segmentsByKey } from "../lensGroup";
import { storyQueries } from "../queries";
import { StoryTrace } from "../StoryTrace";
import { isPositiveId } from "@/shared/lib/ids";
import { getLang, localName, t, tn } from "@/shared/i18n";

function OutletLink({ story, a }: { story: StoryDetail; a: StoryArticle }) {
  const href = safeHref(a.url);
  if (!href) return <span lang={a.language}>{a.title}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" lang={a.language}
      onClick={() => recordRead(a.source_slug, story.id, story.topic_slug)}>
      {a.title}
      <span className="visually-hidden"> {t("(opens {host} in a new tab)", { host: hostOf(a.url) })}</span>
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
        <section key={seg.key} className="headline-column" aria-label={`${seg.label}: ${tn(articles.length, "{n} article", "{n} articles")}`}
          style={{ ["--col-color" as string]: seg.color }}>
          <h3>{seg.label} · {articles.length}</h3>
          {articles.map((a) => (
            <div key={a.id} className="headline">
              <OutletLink story={story} a={a} />
              <span className="headline__meta">
                <Link to={`/sources/${a.source_slug}`}>{a.source_name}</Link> · {formatDateTime(a.published_at)}
                {a.is_first && <> · <strong>{t("first report")}</strong></>}
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
  const valid = isPositiveId(id);
  const query = useApiQuery(storyQueries(id).story, valid);
  const s = query.data;
  const missing = !valid || isNotFound(query.error);
  useTitle(
    missing ? t("Story not found") : (s?.title ?? t("Story")),
    s ? tn(s.source_count, "{n} outlet covered this story.", "{n} outlets covered this story.") : undefined,
    { index: !missing },
  );
  const available = s ? availableLenses([s.coverage]) : null;
  const [lens, setLens] = useLens(available);
  if (missing) {
    return (
      <NotFoundState title={t("Story not found")}>
        {t("This story does not exist, or is no longer shown. Stories are regrouped from time to time, so an old link can point nowhere.")}
      </NotFoundState>
    );
  }
  if (query.isPending) return <LoadingBlock height={320} />;
  if (query.isError || !s) return <ErrorState error={query.error} />;
  const first = s.articles.find((a) => a.is_first) ?? s.articles[0]!;
  const summary = summaryFor(s);

  return (
    <article>
      <header className="story-head">
        <p className="kicker">
          <Link to="/">{t("Stories")}</Link> /{" "}
          {s.topic_slug ? <Link to={`/topics/${s.topic_slug}`}>{localName(s.topic_name, s.topic_name_sq)}</Link> : t("Story")}
        </p>
        <h1 lang={s.language}>{s.title}</h1>
        <p className="story-head__meta">
          <span><strong>{tn(s.source_count, "{n} outlet", "{n} outlets")}</strong> · {tn(s.article_count, "{n} article", "{n} articles")}</span>
          <span>{t("First reported by")} <Link to={`/sources/${first.source_slug}`}>{first.source_name}</Link>, {formatDateTime(first.published_at)}</span>
          <span>{t("Updated {when}", { when: formatRelative(s.last_published_at) })}</span>
          <BlindspotBadges story={s} />
        </p>
        {summary && (
          <p className="story-head__summary">
            <span lang={summary.lang}>{summary.text}</span>{" "}
            <span className="meta">{summary.lang === getLang() ? t("(AI summary)") : t("(AI summary, in English)")}</span>
          </p>
        )}
        <ShareStory id={s.id} title={s.title} />
      </header>

      <div className="feed-layout">
        <div className="stack">
          <Card title={t("How each outlet headlined it")}
            question={t("Every outlet's own headline, linked to the original. Compare the wording.")}
            actions={<LensPicker lens={lens} onChange={setLens} available={available ?? undefined} />}>
            {() => <HeadlineColumns story={s} lens={lens} />}
          </Card>
          <Card title={t("Timeline")} question={t("Who reported it, and when — each mark is one report.")}>
            {() => {
              const segs = segmentsByKey(s.coverage, lens);
              return (
                <>
                  <StoryTrace story={s} lens={lens} />
                  <ol className="timeline">
                    {s.articles.map((a) => (
                      <li key={a.id} style={{ ["--tick" as string]: markColor(segs.get(groupOf(a, lens))) }}>
                        <span>
                          <time dateTime={a.published_at}>{formatDateTime(a.published_at)}</time>{" "}
                          <strong>{a.source_name}</strong>
                          {a.is_first && <span className="meta"> · {t("first report")}</span>}
                        </span>
                        <span><OutletLink story={s} a={a} /> <SentimentChip label={a.sentiment_label} /></span>
                      </li>
                    ))}
                  </ol>
                </>
              );
            }}
          </Card>
          {s.related.length > 0 && (
            <Card title={t("Related stories")} question={t("Stories within three days that name the same people, organisations or places.")}>
              {() => <div>{s.related.map((r) => <StoryCard key={r.id} story={r} lens={lens} compact />)}</div>}
            </Card>
          )}
        </div>

        <aside className="feed-aside" aria-label={t("Coverage details")}>
          <Card title={t("Coverage details")} question={t("Distinct outlets that covered this story.")}>
            {() => (
              <div className="stack">
                {(["perspective", "factuality", "ownership", "region"] as Lens[]).filter((l) => available?.includes(l)).map((l) => (
                  <div key={l} className="stack stack--tight">
                    <h3>{LENS_LABEL[l]}</h3>
                    <StoryCoverage coverage={s.coverage} lens={l} />
                  </div>
                ))}
                <dl className="facts">
                  <dt>{t("Outlets")}</dt><dd>{s.source_count}</dd>
                  <dt>{t("Articles")}</dt><dd>{s.article_count}</dd>
                  <dt>{t("Tone")}</dt><dd>{t("{n} negative · {u} neutral · {p} positive", { n: s.tone.negative, u: s.tone.neutral, p: s.tone.positive })}</dd>
                  <dt>{t("Started")}</dt><dd>{formatDateTime(s.first_published_at)}</dd>
                  <dt>{t("Last update")}</dt><dd>{formatDateTime(s.last_published_at)}</dd>
                </dl>
                <p className="card__foot">
                  {available?.includes("perspective")
                    ? t("Ratings are editorial and belong to the outlet, not to the article.")
                    : t("None of these outlets has a perspective or factuality rating yet.")}{" "}
                  <Link to="/about#ratings">{t("How outlets are rated")}</Link>
                </p>
              </div>
            )}
          </Card>
          <Card title={t("Outlets")} question={t("Their ratings, and where they are based.")}>
            {() => (
              <ul className="plain-list">
                {s.sources.map((src) => {
                  const a = s.articles.find((x) => x.source_slug === src.slug)!;
                  return (
                    <li key={src.slug} className="rating">
                      <span className="dot" style={{ background: BIAS_GROUP_COLOR[biasGroup(src.bias)] }} aria-hidden="true" />
                      <span>
                        <Link to={`/sources/${src.slug}`}>{src.name}</Link>
                        <span className="meta">
                          {" · "}
                          {[
                            src.bias !== "unrated" && BIAS_LABEL[src.bias],
                            a.source_factuality !== "unrated" && t("{level} factuality", { level: FACTUALITY_LABEL[a.source_factuality].toLowerCase() }),
                            src.bias === "unrated" && a.source_factuality === "unrated" && t("not rated yet"),
                            OWNERSHIP_LABEL[a.source_ownership],
                            countryLabel(src.country),
                          ].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
          {(s.entities.length > 0 || s.topics.length > 0) && (
            <Card title={t("Tags")} question={t("Topics and names in this story.")}>
              {() => (
                <div className="chips">
                  {s.topics.map((tp) => <Link key={tp.slug} className="chip" to={`/topics/${tp.slug}`}>{localName(tp.name_en, tp.name_sq)}</Link>)}
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
