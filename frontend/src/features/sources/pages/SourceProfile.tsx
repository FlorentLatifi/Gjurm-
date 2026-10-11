import { Link, useParams } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import { StoryCard } from "@/features/stories";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { useTitle } from "@/shared/hooks/useTitle";
import { ENTITY_TYPE_LABEL, formatDateTime, formatInt, formatPercent, formatScore, safeHref, toneLabel } from "@/shared/lib/format";
import { BIAS_GROUP_COLOR, BIAS_LABEL, biasGroup, countryLabel, FACTUALITY_LABEL, OWNERSHIP_LABEL } from "@/shared/model/ratings";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { StatTile } from "@/ui/StatTile";
import { ErrorState, LoadingBlock } from "@/ui/States";
import { useSourceProfile } from "../api";

/** One outlet, as on Ground News' source pages: ratings, ownership, and how it covers the news. */
export function SourceProfilePage() {
  const slug = useParams().slug ?? "";
  const { filters, apiParams } = useFilters();
  const query = useSourceProfile(slug, { days: apiParams.days });
  const p = query.data;
  useTitle(p?.name ?? "Source", p ? `${p.name}: ratings, ownership and coverage.` : undefined);
  if (query.isPending) return <LoadingBlock height={320} />;
  if (query.isError || !p) return <ErrorState error={query.error} />;
  const href = safeHref(p.homepage_url);
  const rated = p.bias !== "unrated" || p.factuality !== "unrated";

  return (
    <div className="stack">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <p className="rank-meta"><Link to="/sources">Sources</Link> /</p>
          <h1 style={{ marginTop: 4 }}>{p.name}</h1>
          <p>
            {countryLabel(p.country)} · {OWNERSHIP_LABEL[p.ownership]}{p.owner && <> ({p.owner})</>}
            {href && <> · <a href={href} target="_blank" rel="noopener noreferrer">{href.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗</a></>}
          </p>
        </div>
      </div>
      <FilterBar showSources={false} />

      <div className="grid grid--kpi">
        <div className="card stat">
          <span className="stat__label">Perspective</span>
          <span className="stat__value stat__value--text rating">
            <span className="dot" style={{ background: BIAS_GROUP_COLOR[biasGroup(p.bias)] }} aria-hidden="true" />
            {BIAS_LABEL[p.bias]}
          </span>
        </div>
        <StatTile label="Factuality" textValue value={FACTUALITY_LABEL[p.factuality]} />
        <StatTile label="Stories covered" value={formatInt(p.stories)}
          sub={p.coverage_share !== null ? `${formatPercent(p.coverage_share)} of stories several outlets covered` : undefined} />
        <StatTile label="Reported first" value={formatInt(p.first_reports)} sub="multi-outlet stories it published first" />
        <StatTile label="Only here" value={formatInt(p.exclusives)} sub="stories no other followed outlet ran" />
        <StatTile label="Mean tone" value={formatScore(p.avg_sentiment)} sub={`${toneLabel(p.avg_sentiment)} · ${formatInt(p.articles)} articles`} />
      </div>

      <section className="card" aria-labelledby="ratings-heading">
        <h2 id="ratings-heading">About the ratings</h2>
        <p className="card__question">
          {rated
            ? <>Basis: {p.ratings_note}</>
            : <>This outlet has not been rated for perspective or factuality yet. GJURMË only shows ratings that rest on a documented review.</>}{" "}
          <Link to="/about#ratings">How outlets are rated</Link>
        </p>
        {p.last_success_at && <p className="card__foot">Feed last read {formatDateTime(p.last_success_at)}.</p>}
      </section>

      <div className="grid grid--2">
        <Card title="Recent stories" question={`Stories ${p.name} covered, newest first.`}
          empty={!p.recent_stories.length}>
          {() => <div>{p.recent_stories.map((s) => <StoryCard key={s.id} story={s} lens="perspective" compact />)}</div>}
        </Card>
        <div className="stack">
          <Card title="Covers the same stories as" question="Outlets that covered the most stories in common."
            empty={!p.overlap.length}>
            {() => (
              <RankList unit="shared stories" items={p.overlap.map((o) => ({
                key: o.slug, label: o.name, href: withFilters(`/sources/${o.slug}`, filters), value: o.shared,
                sublabel: BIAS_LABEL[o.bias],
              }))} />
            )}
          </Card>
          <Card title="Topic focus" empty={!p.top_topics.length}>
            {() => (
              <RankList unit="articles" items={p.top_topics.map((t) => ({
                key: t.slug, label: t.name_en, value: t.articles,
                href: withFilters(`/topics/${t.slug}`, { ...filters, sources: [p.slug] }),
              }))} />
            )}
          </Card>
          <Card title="Most mentioned" empty={!p.top_entities.length}>
            {() => (
              <RankList unit="articles" items={p.top_entities.map((e) => ({
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
