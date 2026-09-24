import { Link } from "react-router-dom";

import { useSources } from "../api/hooks";
import { Card } from "../components/Card";
import { SentimentBar } from "../components/charts";
import { FilterBar } from "../components/FilterBar";
import { RankList } from "../components/lists";
import { useFilters, withFilters } from "../lib/filters";
import { formatDateTime, formatInt, formatPercent, formatScore, safeHref } from "../lib/format";
import { useTitle } from "../lib/useTitle";

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
          <p>How outlets differ. “Original” is the share of an outlet’s articles that were not a
            near-verbatim copy of a headline already published elsewhere.</p>
        </div>
      </div>
      <FilterBar showSources={false} />
      <div className="stack">
        <Card title="Volume by outlet" question="Who publishes the most?" query={sources}
          empty={!rows.some((s) => s.articles)}>
          {() => (
            <RankList unit="articles" items={rows.filter((s) => s.articles).map((s) => ({
              key: s.slug, label: s.name, value: s.articles, href: withFilters("/", { ...filters, sources: [s.slug] }),
              meta: <> · {s.per_day?.toFixed(1)}/day</>,
            }))} />
          )}
        </Card>
        <Card title="Outlet profiles" question="How do outlets differ in originality, tone and topic focus?"
          query={sources} empty={!rows.length}>
          {() => (
            <div className="table-wrap">
              <table>
                <caption>Last {filters.days} days</caption>
                <thead>
                  <tr>
                    <th scope="col">Outlet</th>
                    <th className="num" scope="col">Articles</th>
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
                        {safeHref(s.homepage_url) ? (
                          <a href={safeHref(s.homepage_url)} target="_blank" rel="noopener noreferrer">{s.name}</a>
                        ) : s.name}
                        <div className="rank-meta">{s.country} · {s.language}</div>
                      </td>
                      <td className="num">{formatInt(s.articles)}</td>
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
