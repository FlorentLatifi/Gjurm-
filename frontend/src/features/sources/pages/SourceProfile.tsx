import { Link, useParams, useSearchParams } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import { StoryCard } from "@/features/stories";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { isNotFound } from "@/shared/api/client";
import { useTitle } from "@/shared/hooks/useTitle";
import {
  ENTITY_TYPE_LABEL,
  formatDateTime,
  formatInt,
  formatPercent,
  formatScore,
  safeHref,
  toneLabel,
} from "@/shared/lib/format";
import {
  availableLenses,
  BIAS_GROUP_COLOR,
  BIAS_LABEL,
  biasGroup,
  countryLabel,
  FACTUALITY_LABEL,
  OWNERSHIP_LABEL,
} from "@/shared/model/ratings";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { StatTile } from "@/ui/StatTile";
import { ErrorState, LoadingBlock, NotFoundState } from "@/ui/States";
import { useApiQuery } from "@/shared/query/apiQuery";
import { validSlug } from "../api";
import { sourceProfileQueries } from "../queries";
import { localName, t, tn } from "@/shared/i18n";

/** One outlet, as on Ground News' source pages: ratings, ownership, and how it covers the news. */
export function SourceProfilePage() {
  const slug = useParams().slug ?? "";
  const { filters } = useFilters();
  const [search] = useSearchParams();
  const query = useApiQuery(sourceProfileQueries(slug, search).profile, validSlug(slug));
  const p = query.data;
  const missing = !validSlug(slug) || isNotFound(query.error);
  useTitle(
    missing ? t("Outlet not found") : (p?.name ?? t("Source")),
    p ? t("{outlet}: ratings, ownership and coverage.", { outlet: p.name }) : undefined,
    { index: !missing },
  );
  if (missing) return <NotFoundState title={t("Outlet not found")}>{t("GJURMË does not follow this outlet.")}</NotFoundState>;
  if (query.isPending) return <LoadingBlock height={320} />;
  if (query.isError || !p) return <ErrorState error={query.error} />;
  const href = safeHref(p.homepage_url);
  const rated = p.bias !== "unrated" || p.factuality !== "unrated";

  return (
    <div className="stack">
      <div className="page-head mb-0">
        <div>
          <p className="rank-meta"><Link to="/sources">{t("Sources")}</Link> /</p>
          <h1>{p.name}</h1>
          <p>
            {countryLabel(p.country)} · {OWNERSHIP_LABEL[p.ownership]}{p.owner && <> ({p.owner})</>}
            {href && <> · <a href={href} target="_blank" rel="noopener noreferrer">{href.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗</a></>}
          </p>
        </div>
      </div>
      <FilterBar showSources={false} />

      <div className="grid grid--kpi">
        <div className="card stat">
          <span className="stat__label">{t("Perspective")}</span>
          <span className="stat__value stat__value--text rating">
            <span className="dot" style={{ background: BIAS_GROUP_COLOR[biasGroup(p.bias)] }} aria-hidden="true" />
            {BIAS_LABEL[p.bias]}
          </span>
        </div>
        <StatTile label={t("Factuality")} textValue value={FACTUALITY_LABEL[p.factuality]} />
        <StatTile label={t("Stories covered")} value={formatInt(p.stories)}
          sub={p.coverage_share !== null ? t("{share} of stories several outlets covered", { share: formatPercent(p.coverage_share) }) : undefined} />
        <StatTile label={t("Reported first")} value={formatInt(p.first_reports)} sub={t("multi-outlet stories it published first")} />
        <StatTile label={t("Only here")} value={formatInt(p.exclusives)} sub={t("stories no other followed outlet ran")} />
        <StatTile label={t("Mean tone")} value={formatScore(p.avg_sentiment)} sub={`${toneLabel(p.avg_sentiment)} · ${tn(p.articles, "{n} article", "{n} articles")}`} />
      </div>

      <section className="card" aria-labelledby="ratings-heading">
        <h2 id="ratings-heading">{t("About the ratings")}</h2>
        <p className="card__question">
          {rated
            ? <>{t("Basis:")} <span lang="en">{p.ratings_note}</span></>
            : t("This outlet has not been rated for perspective or factuality yet. GJURMË only shows ratings that rest on a documented review.")}{" "}
          <Link to="/about#ratings">{t("How outlets are rated")}</Link>
        </p>
        {p.last_success_at && <p className="card__foot">{t("Feed last read {time}.", { time: formatDateTime(p.last_success_at) })}</p>}
      </section>

      <div className="grid grid--2">
        <Card title={t("Recent stories")} question={t("Stories {outlet} covered, newest first.", { outlet: p.name })}
          empty={!p.recent_stories.length}>
          {() => {
            const lens = availableLenses(p.recent_stories.map((s) => s.coverage)).includes("perspective") ? "perspective" : "region";
            return <div>{p.recent_stories.map((s) => <StoryCard key={s.id} story={s} lens={lens} compact />)}</div>;
          }}
        </Card>
        <div className="stack">
          <Card title={t("Covers the same stories as")} question={t("Outlets that covered the most stories in common.")}
            empty={!p.overlap.length}>
            {() => (
              <RankList unit={(n) => tn(n, "{n} shared story", "{n} shared stories")} items={p.overlap.map((o) => ({
                key: o.slug, label: o.name, href: withFilters(`/sources/${o.slug}`, filters), value: o.shared,
                sublabel: BIAS_LABEL[o.bias],
              }))} />
            )}
          </Card>
          <Card title={t("Topic focus")} empty={!p.top_topics.length}>
            {() => (
              <RankList unit={(n) => tn(n, "{n} article", "{n} articles")} items={p.top_topics.map((tp) => ({
                key: tp.slug, label: localName(tp.name_en, tp.name_sq), value: tp.articles,
                href: withFilters(`/topics/${tp.slug}`, { ...filters, sources: [p.slug] }),
              }))} />
            )}
          </Card>
          <Card title={t("Most mentioned")} empty={!p.top_entities.length}>
            {() => (
              <RankList unit={(n) => tn(n, "{n} article", "{n} articles")} items={p.top_entities.map((e) => ({
                key: e.id, label: e.name, value: e.mentions, sublabel: ENTITY_TYPE_LABEL[e.type],
                href: withFilters(`/entities/${e.id}`, filters),
              }))} />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
