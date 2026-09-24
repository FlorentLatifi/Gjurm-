import { Link, useParams } from "react-router-dom";

import { useArticles, useTopic, useTopics } from "../api/hooks";
import { Card } from "../components/Card";
import { DailyLine, SentimentBar } from "../components/charts";
import { FilterBar } from "../components/FilterBar";
import { ArticleList, RankList } from "../components/lists";
import { ErrorState } from "../components/States";
import { useFilters, withFilters } from "../lib/filters";
import {
  ENTITY_TYPE_LABEL,
  formatChange,
  formatDay,
  formatInt,
  formatPercent,
  formatScore,
  hasComparableHistory,
} from "../lib/format";
import { useTitle } from "../lib/useTitle";

export function TopicsPage() {
  useTitle("Topics", "Which topics dominate Albanian-language news, and how each is trending.");
  const { filters, apiParams } = useFilters();
  const topics = useTopics(apiParams);
  const rows = topics.data ?? [];
  const comparable = hasComparableHistory(rows, (t) => t.articles, (t) => t.previous);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Topics</h1>
          <p>
            Every article gets one primary topic from a fixed list of {rows.length || 19} topics, so
            counts are comparable over time. Change compares with the previous {filters.days} days
            {comparable ? "." : " — not available until enough history has been collected."}
          </p>
        </div>
      </div>
      <FilterBar />
      <Card title="Topic ranking" question="Which topics dominate, and which are growing?" query={topics}
        empty={!rows.some((t) => t.articles)}>
        {() => (
          <div className="table-wrap">
            <table>
              <caption>Primary topic of analysed articles, last {filters.days} days</caption>
              <thead>
                <tr>
                  <th scope="col">Topic</th>
                  <th className="num" scope="col">Articles</th>
                  <th className="num" scope="col">Share</th>
                  <th className="num" scope="col">Change</th>
                  <th scope="col" style={{ minWidth: 120 }}>Tone mix</th>
                  <th className="num" scope="col">Mean tone</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.slug}>
                    <td>
                      <Link to={withFilters(`/topics/${t.slug}`, filters)}>{t.name_en}</Link>
                      <div className="rank-meta" lang="sq">{t.name_sq}</div>
                    </td>
                    <td className="num">{formatInt(t.articles)}</td>
                    <td className="num">{formatPercent(t.share, 1)}</td>
                    <td className="num">{comparable && (t.articles || t.previous) ? formatChange(t.change) : "—"}</td>
                    <td>
                      <SentimentBar negative={t.negative} positive={t.positive}
                        neutral={Math.max(0, t.articles - t.negative - t.positive)} />
                    </td>
                    <td className="num">{formatScore(t.avg_sentiment)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

export function TopicPage() {
  const { slug = "" } = useParams();
  const { filters, apiParams } = useFilters();
  const topic = useTopic(slug, apiParams);
  const articles = useArticles({ ...apiParams, topic: slug, page_size: 10 });
  const t = topic.data?.topic;
  useTitle(t ? t.name_en : "Topic", t?.description);
  if (topic.isError) return <ErrorState error={topic.error} onRetry={() => topic.refetch()} />;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="rank-meta"><Link to={withFilters("/topics", filters)}>Topics</Link> /</p>
          <h1>{t?.name_en ?? "Topic"}</h1>
          {t && <p><span lang="sq">{t.name_sq}</span> — {t.description}</p>}
        </div>
      </div>
      <FilterBar />
      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title="Articles per day" question="How much coverage does this topic get over time?"
          query={topic} empty={!topic.data?.series.some((d) => d.articles)}
          method="Counts articles with this topic as primary or secondary topic."
          table={() => (
            <table><caption>Articles per day</caption>
              <thead><tr><th scope="col">Day</th><th className="num" scope="col">Articles</th>
                <th className="num" scope="col">Mean tone</th></tr></thead>
              <tbody>{topic.data?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{d.articles}</td>
                  <td className="num">{formatScore(d.avg_sentiment)}</td></tr>))}</tbody>
            </table>
          )}>
          {() => <DailyLine data={topic.data!.series} dataKey="articles" label="Articles" />}
        </Card>
        <Card title="Who is involved" question="Which people, organisations and places appear in this topic?"
          query={topic} empty={!topic.data?.top_entities.length}>
          {() => (
            <RankList unit="articles" items={topic.data!.top_entities.slice(0, 10).map((e) => ({
              key: e.id, label: e.name, href: withFilters(`/entities/${e.id}`, filters), value: e.mentions,
              sublabel: ENTITY_TYPE_LABEL[e.type],
            }))} />
          )}
        </Card>
      </div>
      <div className="grid grid--2">
        <Card title="By outlet" question="Which outlets cover this topic most, and in what tone?" query={topic}
          empty={!topic.data?.sources.length}>
          {() => (
            <table>
              <thead><tr><th scope="col">Outlet</th><th className="num" scope="col">Articles</th>
                <th className="num" scope="col">Mean tone</th></tr></thead>
              <tbody>{topic.data!.sources.map((s) => (
                <tr key={s.slug}><td>{s.name}</td><td className="num">{formatInt(s.articles)}</td>
                  <td className="num">{formatScore(s.avg_sentiment)}</td></tr>))}</tbody>
            </table>
          )}
        </Card>
        <Card title="Recent articles" query={articles} empty={!articles.data?.items.length}
          actions={<Link className="btn btn--ghost btn--sm" to={withFilters("/articles", filters, { topic: slug })}>All</Link>}>
          {() => <ArticleList items={articles.data!.items} />}
        </Card>
      </div>
    </>
  );
}
