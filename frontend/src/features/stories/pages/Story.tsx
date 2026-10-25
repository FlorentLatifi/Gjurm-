import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { isNotFound } from "@/shared/api/client";
import type { StoryArticle, StoryDetail } from "@/shared/api/types";
import { useTitle } from "@/shared/hooks/useTitle";
import { useApiQuery } from "@/shared/query/apiQuery";
import { ENTITY_TYPE_LABEL, formatDateTime, formatPercent, formatRelative, hostOf, safeHref, summaryFor } from "@/shared/lib/format";
import {
  BIAS_GROUP_COLOR,
  BIAS_LABEL,
  biasGroup,
  countryLabel,
  FACTUALITY_LABEL,
  type Lens,
  availableLenses,
  leadingSegment,
  OWNERSHIP_LABEL,
  type Segment,
  segments,
} from "@/shared/model/ratings";
import { recordRead } from "@/stores/reading";
import { Card } from "@/ui/Card";
import { SentimentChip } from "@/ui/SentimentChip";
import { ErrorState, LoadingBlock, NotFoundState } from "@/ui/States";
import { BlindspotBadges, initials, StoryCard } from "../StoryCard";
import { LensPicker, StoryCoverage } from "../StoryCoverage";
import { ShareStory } from "../ShareStory";
import { useLens } from "../useLens";
import { groupOf, markColor, segmentsByKey } from "../lensGroup";
import { storyQueries } from "../queries";
import { StoryTrace } from "../StoryTrace";
import { isPositiveId } from "@/shared/lib/ids";
import { getLang, labels, localName, t, tn } from "@/shared/i18n";

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

const DISTRIBUTION_TITLE = labels({
  perspective: "Bias distribution",
  region: "Region distribution",
  ownership: "Ownership distribution",
  factuality: "Factuality distribution",
});
const UNTRACKED = labels({
  perspective: "Untracked bias",
  region: "Other countries",
  ownership: "Unknown ownership",
  factuality: "Untracked factuality",
});

/** The tabs of the story's sides: Left, Center, Right on Ground News; here, the lens's groups. */
function sidesOf(story: StoryDetail, lens: Lens): Segment[] {
  const all = segments(story.coverage, lens).filter((seg) => !seg.hatched);
  // perspective always shows its three sides, so a side nobody covered is visible as empty
  return lens === "perspective" ? all : all.filter((seg) => seg.value > 0);
}

/** One side's coverage: its outlets' own headlines, linked to the originals. */
function SideHeadlines({ story, lens, side }: { story: StoryDetail; lens: Lens; side: Segment }) {
  const articles = story.articles.filter((a) => groupOf(a, lens) === side.key);
  if (!articles.length) {
    return (
      <p className="side-empty">
        {t("No outlet in this group covered the story — a blindspot for its readers.")}
      </p>
    );
  }
  return (
    <ul className="side-headlines">
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
  );
}

/** Ground News' coverage details: totals per side, last update and the leading side. */
function CoverageDetails({ story, lens }: { story: StoryDetail; lens: Lens }) {
  const parts = segments(story.coverage, lens);
  const lead = leadingSegment(parts);
  return (
    <section className="details-panel" aria-labelledby="details-heading">
      <h2 id="details-heading">{t("Coverage details")}</h2>
      <dl>
        <div><dt>{t("Total news sources")}</dt><dd>{story.source_count}</dd></div>
        {parts.filter((p) => p.value > 0 || (lens === "perspective" && !p.hatched)).map((p) => (
          <div key={p.key}><dt>{p.label}</dt><dd>{p.value}</dd></div>
        ))}
        <div><dt>{t("Articles")}</dt><dd>{story.article_count}</dd></div>
        <div><dt>{t("Last updated")}</dt><dd>{formatRelative(story.last_published_at)}</dd></div>
        {lead && (
          <div><dt>{t("Distribution")}</dt><dd>{formatPercent(lead.share)} {lead.segment.label}</dd></div>
        )}
      </dl>
    </section>
  );
}

/** An outlet as Ground News shows it, a round logo; here its initials, linked to its profile. */
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

function Monogram({ src }: { src: StoryDetail["sources"][number] }) {
  return (
    <li><Link className="monogram" to={`/sources/${src.slug}`} title={src.name} aria-label={src.name}>{initials(src.name)}</Link></li>
  );
}

/** Ground News' bias distribution: the bar, then the outlets in one column per side. */
function Distribution({ story, lens }: { story: StoryDetail; lens: Lens }) {
  const parts = segments(story.coverage, lens);
  const lead = leadingSegment(parts);
  const groupOfSource = new Map(story.sources.map((src) => {
    const a = story.articles.find((x) => x.source_slug === src.slug)!;
    return [src.slug, groupOf(a, lens)];
  }));
  const outletsOf = (key: string) => story.sources.filter((src) => groupOfSource.get(src.slug) === key);
  const columns = parts.filter((p) => !p.hatched && (p.value > 0 || lens === "perspective"));
  const untracked = story.sources.filter((src) => parts.find((p) => p.key === groupOfSource.get(src.slug))?.hatched ?? true);
  return (
    <section className="distribution" aria-labelledby="distribution-heading">
      <h2 id="distribution-heading">{DISTRIBUTION_TITLE[lens]}</h2>
      {lead && (
        <p className="distribution__lead">
          {t("{share} of the sources are {side}", { share: formatPercent(lead.share), side: lead.segment.label })}
        </p>
      )}
      <StoryCoverage coverage={story.coverage} lens={lens} size="lg" labels="inside" />
      <div className="distribution__columns">
        {columns.map((col) => {
          const outlets = outletsOf(col.key);
          return (
            <div key={col.key} className="distribution__column" style={{ ["--col-color" as string]: col.color }}>
              <h3 className="visually-hidden">{col.label}: {tn(outlets.length, "{n} outlet", "{n} outlets")}</h3>
              <ul>
                {outlets.slice(0, 5).map((src) => <Monogram key={src.slug} src={src} />)}
                {outlets.length > 5 && <li><span className="monogram monogram--more">+{outlets.length - 5}</span></li>}
              </ul>
              <span className="distribution__label" aria-hidden="true">{col.label}</span>
            </div>
          );
        })}
      </div>
      {untracked.length > 0 && (
        <div className="distribution__untracked">
          <h3>{UNTRACKED[lens]}</h3>
          <ul>{untracked.map((src) => <Monogram key={src.slug} src={src} />)}</ul>
        </div>
      )}
    </section>
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
  // the chosen side, per story and lens; by default the side that covered it most
  const [chosen, setChosen] = useState<{ key: string; at: string } | null>(null);
  const [compare, setCompare] = useState(false);
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
  const first = s.articles.find((a) => a.is_first) ?? s.articles[0]!;
  const summary = summaryFor(s);
  const sides = sidesOf(s, lens);
  const here = `${s.id}:${lens}`;
  const lead = leadingSegment(segments(s.coverage, lens));
  const sideKey = chosen?.at === here ? chosen.key : (lead?.segment.key ?? sides[0]?.key);
  const side = sides.find((x) => x.key === sideKey) ?? sides[0];

  return (
    <article className="story-page">
      <div className="story-page__main">
        <header className="story-head">
          <div className="story-head__top">
            <p className="story-head__meta">
              <span>{t("Published {when}", { when: formatRelative(s.first_published_at) })}</span>
              {s.topic_slug && <Link to={`/topics/${s.topic_slug}`}>{localName(s.topic_name, s.topic_name_sq)}</Link>}
              <span>{t("Updated {when}", { when: formatRelative(s.last_published_at) })}</span>
            </p>
            <ShareStory id={s.id} title={s.title} />
          </div>
          <h1 lang={s.language}>{s.title}</h1>
          <p className="story-head__meta">
            <span>{t("First reported by")} <Link to={`/sources/${first.source_slug}`}>{first.source_name}</Link>, {formatDateTime(first.published_at)}</span>
            <span><strong>{tn(s.source_count, "{n} outlet", "{n} outlets")}</strong> · {tn(s.article_count, "{n} article", "{n} articles")}</span>
            <BlindspotBadges story={s} />
          </p>
        </header>

        <StoryPhoto story={s} />

        <div className="side-bar">
          {side && (
            <div className="side-tabs" role="group" aria-label={t("Coverage from")}>
              {sides.map((x) => (
                <button key={x.key} type="button" aria-pressed={!compare && x.key === side.key}
                  style={{ ["--side-color" as string]: x.color }}
                  onClick={() => { setChosen({ key: x.key, at: here }); setCompare(false); }}>
                  {x.label}
                </button>
              ))}
            </div>
          )}
          <button type="button" className="btn side-compare" aria-pressed={compare} onClick={() => setCompare((c) => !c)}>
            <span aria-hidden="true" className="side-compare__icon">⇆</span> {t("Compare headlines")}
          </button>
        </div>

        {summary && (
          <div className="story-summary">
            <p>
              <span lang={summary.lang}>{summary.text}</span>{" "}
              <span className="meta">{summary.lang === getLang() ? t("(AI summary)") : t("(AI summary, in English)")}</span>
            </p>
          </div>
        )}

        {compare || !side ? (
          <HeadlineColumns story={s} lens={lens} />
        ) : (
          <SideHeadlines story={s} lens={lens} side={side} />
        )}

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

      <aside className="story-page__aside" aria-label={t("Coverage details")}>
        <div className="lens-row">
          <span className="rank-meta">{t("Split coverage by")}</span>
          <LensPicker lens={lens} onChange={setLens} available={available ?? undefined} />
        </div>
        <CoverageDetails story={s} lens={lens} />
        <Distribution story={s} lens={lens} />
        <p className="card__foot">
          {available?.includes("perspective")
            ? t("Ratings are editorial and belong to the outlet, not to the article.")
            : t("None of these outlets has a perspective or factuality rating yet.")}{" "}
          <Link to="/about#ratings">{t("How outlets are rated")}</Link>
        </p>
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
    </article>
  );
}
