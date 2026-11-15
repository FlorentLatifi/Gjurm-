import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { isNotFound } from "@/shared/api/client";
import type { StoryArticle, StoryDetail } from "@/shared/api/types";
import { useTitle } from "@/shared/hooks/useTitle";
import { useApiQuery } from "@/shared/query/apiQuery";
import { ENTITY_TYPE_LABEL, formatDateTime, formatRelative, hostOf, safeHref, summaryFor } from "@/shared/lib/format";
import {
  availableLenses,
  BIAS_GROUP_COLOR,
  BIAS_LABEL,
  biasGroup,
  countryLabel,
  FACTUALITY_LABEL,
  type Lens,
  LENS_LABEL,
  OWNERSHIP_LABEL,
  type Segment,
  segments,
} from "@/shared/model/ratings";
import { recordRead } from "@/stores/reading";
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

/** The columns of the comparison: perspective always shows its three sides, so a side nobody covered is seen empty. */
function sidesOf(story: StoryDetail, lens: Lens): Segment[] {
  const all = segments(story.coverage, lens);
  return lens === "perspective" ? all.filter((seg) => !seg.hatched || seg.value > 0) : all.filter((seg) => seg.value > 0);
}

/**
 * Every outlet's own headline for the same story, side by side in one column per group of the
 * chosen lens, each linked to the original. A wide column sets its headlines in two.
 */
function HeadlineColumns({ story, lens }: { story: StoryDetail; lens: Lens }) {
  const columns = sidesOf(story, lens).map((seg) => ({ seg, articles: story.articles.filter((a) => groupOf(a, lens) === seg.key) }));
  return (
    <div className="headline-columns">
      {columns.map(({ seg, articles }) => (
        <section key={seg.key} className="headline-column" aria-label={`${seg.label}: ${tn(articles.length, "{n} article", "{n} articles")}`}
          style={{ ["--col-color" as string]: markColor(seg), ["--col-grow" as string]: Math.min(Math.max(articles.length, 1), 3) }}>
          <h3 className="caps"><span>{seg.label}</span><span>{articles.length}</span></h3>
          {articles.length ? (
            <ul className="headline-column__list">
              {articles.map((a) => (
                <li key={a.id} className="headline">
                  <OutletLink story={story} a={a} />
                  <span className="headline__meta">
                    <Link to={`/sources/${a.source_slug}`}>{a.source_name}</Link> · {formatDateTime(a.published_at)}
                    {a.is_first && <> · <strong>{t("first report")}</strong></>}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="side-empty">{t("No outlet in this group covered the story — a blindspot for its readers.")}</p>
          )}
        </section>
      ))}
    </div>
  );
}

/** The photo an outlet gave this story in its own feed, credited and linked to its article. */
function StoryPhoto({ story }: { story: StoryDetail }) {
  const [broken, setBroken] = useState(false);
  const from = story.articles.find((a) => a.image_url === story.image_url);
  if (!story.image_url || !from || broken) return null;
  return (
    <figure className="story-photo">
      <img src={story.image_url} alt="" decoding="async" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
      <figcaption>
        {t("Photo:")} <a href={from.url} target="_blank" rel="noopener noreferrer">{from.source_name}</a>
      </figcaption>
    </figure>
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
  // A story merged into another one answers with that story: show it under its own URL.
  if (s.id !== id) return <Navigate to={`/stories/${s.id}`} replace />;
  // none when the outlets' times cannot tell who was first (an estimated time close to the earliest)
  const first = s.articles.find((a) => a.is_first);
  const summary = summaryFor(s);
  const segs = segmentsByKey(s.coverage, lens);
  const others = (available ?? []).filter((l) => l !== lens);

  return (
    <article className="story-page">
      <header className="story-head">
        <p className="story-head__crumb">
          <Link to="/">← {t("Top stories")}</Link>
          {s.topic_slug && <Link className="kicker" to={`/topics/${s.topic_slug}`}>{localName(s.topic_name, s.topic_name_sq)}</Link>}
        </p>
        <h1 lang={s.language}>{s.title}</h1>
        {summary && (
          <p className="story-summary">
            <span lang={summary.lang}>{summary.text}</span>{" "}
            <span className="meta">{summary.lang === getLang() ? t("(AI summary)") : t("(AI summary, in English)")}</span>
          </p>
        )}
        <p className="story-head__meta">
          {first ? (
            <span>{t("First reported by")} <Link to={`/sources/${first.source_slug}`}>{first.source_name}</Link>, {formatDateTime(first.published_at)}</span>
          ) : (
            <span>{t("First reported {when} (which outlet was first is not known)", { when: formatDateTime(s.first_published_at) })}</span>
          )}
          <span><strong>{tn(s.source_count, "{n} outlet", "{n} outlets")}</strong> · {tn(s.article_count, "{n} article", "{n} articles")}</span>
          <span>{t("Updated {when}", { when: formatRelative(s.last_published_at) })}</span>
        </p>
        {s.blindspots.length > 0 && <p className="story-card__badges"><BlindspotBadges story={s} /></p>}
        <ShareStory id={s.id} title={s.title} />
      </header>

      <StoryPhoto story={s} />

      <section className="story-cov" aria-labelledby="coverage-heading">
        <div className="sec-head">
          <h2 id="coverage-heading">{t("Who covered it")}</h2>
          <LensPicker lens={lens} onChange={setLens} available={available ?? undefined} />
        </div>
        <StoryCoverage coverage={s.coverage} lens={lens} size="lg" labels="shares" missing={s.blindspots} />
        <p className="story-cov__note">
          {available?.includes("perspective")
            ? t("Ratings are editorial and belong to the outlet, not to the article.")
            : t("None of these outlets has a perspective or factuality rating yet.")}{" "}
          <Link to="/about#ratings">{t("How outlets are rated")}</Link>
        </p>
      </section>

      <section className="story-compare" aria-labelledby="compare-heading">
        <div className="sec-head">
          <h2 id="compare-heading">{t("Compare headlines")}</h2>
          <p>{tn(s.article_count, "{n} article", "{n} articles")}</p>
        </div>
        <HeadlineColumns story={s} lens={lens} />
      </section>

      {others.length > 0 && (
        <section className="story-splits" aria-labelledby="splits-heading">
          <div className="sec-head"><h2 id="splits-heading">{t("Other splits")}</h2></div>
          {others.map((l) => (
            <div key={l} className="story-splits__one">
              <h3 className="caps">{LENS_LABEL[l]}</h3>
              <StoryCoverage coverage={s.coverage} lens={l} size="sm" labels="nonzero" />
            </div>
          ))}
        </section>
      )}

      <section className="story-trail" aria-labelledby="timeline-heading">
        <div className="sec-head">
          <h2 id="timeline-heading">{t("Timeline")}</h2>
          <p>{t("Who reported it, and when — each mark is one report.")}</p>
        </div>
        <StoryTrace story={s} lens={lens} />
        <ol className="timeline">
          {s.articles.map((a) => (
            <li key={a.id} style={{ ["--tick" as string]: markColor(segs.get(groupOf(a, lens))) }}>
              <time dateTime={a.published_at}>{formatDateTime(a.published_at)}</time>
              <span>
                <strong>{a.source_name}</strong>
                {a.is_first && <span className="meta"> · {t("first report")}</span>}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className="story-outlets" aria-labelledby="outlets-heading">
        <div className="sec-head">
          <h2 id="outlets-heading">{t("Outlets")}</h2>
          <p>{t("Their ratings, and where they are based.")}</p>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">{t("Outlet")}</th>
                <th scope="col">{LENS_LABEL.perspective}</th>
                <th scope="col" className="wide-only">{LENS_LABEL.factuality}</th>
                <th scope="col" className="wide-only">{LENS_LABEL.ownership}</th>
                <th scope="col">{LENS_LABEL.region}</th>
              </tr>
            </thead>
            <tbody>
              {s.sources.map((src) => {
                const a = s.articles.find((x) => x.source_slug === src.slug)!;
                return (
                  <tr key={src.slug}>
                    <th scope="row"><Link to={`/sources/${src.slug}`}>{src.name}</Link></th>
                    <td>
                      <span className={`swatch ${src.bias === "unrated" ? "seg--hatched" : ""}`}
                        style={{ background: BIAS_GROUP_COLOR[biasGroup(src.bias)] }} aria-hidden="true" />
                      {src.bias === "unrated" ? t("not rated yet") : BIAS_LABEL[src.bias]}
                    </td>
                    <td className="wide-only">{FACTUALITY_LABEL[a.source_factuality]}</td>
                    <td className="wide-only">{OWNERSHIP_LABEL[a.source_ownership]}</td>
                    <td>{countryLabel(src.country)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {(s.entities.length > 0 || s.topics.length > 0) && (
        <section className="story-tags" aria-labelledby="tags-heading">
          <div className="sec-head">
            <h2 id="tags-heading">{t("Tags")}</h2>
            <p>{t("Topics and names in this story.")}</p>
          </div>
          <div className="chips">
            {s.topics.map((tp) => <Link key={tp.slug} className="chip" to={`/topics/${tp.slug}`}>{localName(tp.name_en, tp.name_sq)}</Link>)}
            {s.entities.map((e) => (
              <Link key={e.id} className="chip" to={`/entities/${e.id}`}>{e.name} · {ENTITY_TYPE_LABEL[e.type]}</Link>
            ))}
          </div>
        </section>
      )}

      {s.related.length > 0 && (
        <section className="story-related" aria-labelledby="related-heading">
          <div className="sec-head">
            <h2 id="related-heading">{t("Related stories")}</h2>
            <p>{t("Stories within three days that name the same people, organisations or places.")}</p>
          </div>
          <div className="story-related__list">{s.related.map((r) => <StoryCard key={r.id} story={r} lens={lens} compact />)}</div>
        </section>
      )}
    </article>
  );
}
