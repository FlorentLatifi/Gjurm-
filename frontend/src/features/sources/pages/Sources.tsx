import { Link } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { useTitle } from "@/shared/hooks/useTitle";
import { formatDateTime, formatInt, formatPercent, formatScore } from "@/shared/lib/format";
import { BIAS_GROUP_COLOR, BIAS_LABEL, biasGroup, countryLabel, FACTUALITY_LABEL, OWNERSHIP_LABEL } from "@/shared/model/ratings";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { SentimentBar } from "@/ui/charts";
import { useSources } from "../api";

export default function SourcesPage() {
  useTitle("Sources", "How Albanian-language outlets differ in volume, topics and tone.");
  const { filters, apiParams } = useFilters();
  const sources = useSources(apiParams);
  const rows = sources.data ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Sources</h1>
          <p>How outlets differ, and how they are rated. “Original” is the share of an outlet’s
            articles that were not a near-verbatim copy of a headline already published elsewhere;
            “First” counts the stories several outlets covered that this one published first.{" "}
            <Link to="/about#ratings">How outlets are rated</Link></p>
        </div>
      </div>
      <FilterBar showSources={false} />
      <div className="stack">
        <Card title="Volume by outlet" question="Who publishes the most?" query={sources}
          empty={!rows.some((s) => s.articles)}>
          {() => (
            <RankList unit="articles" items={rows.filter((s) => s.articles).map((s) => ({
              key: s.slug, label: s.name, value: s.articles, href: withFilters(`/sources/${s.slug}`, filters),
              meta: <> · {s.per_day?.toFixed(1)}/day</>,
            }))} />
          )}
        </Card>
        <Card title="Who breaks the news" question="Stories covered by two or more outlets: who published first?"
          query={sources} empty={!rows.some((s) => s.first_reports)}
          emptyText="No story was covered by two or more outlets in this period yet.">
          {() => (
            <RankList unit="first reports" items={rows.filter((s) => s.first_reports).sort((a, b) => b.first_reports - a.first_reports).map((s) => ({
              key: s.slug, label: s.name, value: s.first_reports, href: withFilters(`/sources/${s.slug}`, filters),
              meta: <> · {formatInt(s.stories)} stories covered</>,
            }))} />
          )}
        </Card>
        <Card title="Outlet profiles" question="How do outlets differ in ratings, originality, tone and topic focus?"
          query={sources} empty={!rows.length}>
          {() => (
            <div className="table-wrap">
              <table>
                <caption>Last {filters.days} days</caption>
                <thead>
                  <tr>
                    <th scope="col">Outlet</th>
                    <th scope="col">Perspective</th>
                    <th scope="col">Factuality</th>
                    <th scope="col">Ownership</th>
                    <th className="num" scope="col">Articles</th>
                    <th className="num" scope="col">Stories</th>
                    <th className="num" scope="col">First</th>
                    <th className="num" scope="col">Original</th>
                    <th scope="col" style={{ minWidth: 120 }}>Tone mix</th>
                    <th className="num" scope="col">Mean tone</th>
                    <th scope="col">Top topics</th>
                    <th scope="col">Feed</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => (
                    <tr key={s.slug}>
                      <td>
                        <Link to={withFilters(`/sources/${s.slug}`, filters)}>{s.name}</Link>
                        <div className="rank-meta">{countryLabel(s.country)} · {s.language}</div>
                      </td>
                      <td>
                        <span className="rating">
                          <span className="dot" style={{ background: BIAS_GROUP_COLOR[biasGroup(s.bias)] }} aria-hidden="true" />
                          {BIAS_LABEL[s.bias]}
                        </span>
                      </td>
                      <td>{FACTUALITY_LABEL[s.factuality]}</td>
                      <td>{OWNERSHIP_LABEL[s.ownership]}</td>
                      <td className="num">{formatInt(s.articles)}</td>
                      <td className="num">{formatInt(s.stories)}</td>
                      <td className="num">{formatInt(s.first_reports)}</td>
                      <td className="num">{s.articles ? formatPercent(s.original / s.articles) : "—"}</td>
                      <td><SentimentBar negative={s.negative} neutral={s.neutral} positive={s.positive} /></td>
                      <td className="num">{formatScore(s.avg_sentiment)}</td>
                      <td>
                        <span style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                          {s.top_topics.slice(0, 3).map((t) => (
                            <Link key={t.slug} className="chip" to={withFilters(`/topics/${t.slug}`, { ...filters, sources: [s.slug] })}>
                              {t.slug.replace(/_/g, " ")}
                            </Link>
                          ))}
                        </span>
                      </td>
                      <td className="rank-meta">
                        {s.is_active ? (s.consecutive_failures ? `retrying (${s.consecutive_failures})` : "active")
                          : "paused"}
                        <div>{s.last_success_at ? `ok ${formatDateTime(s.last_success_at)}` : ""}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
