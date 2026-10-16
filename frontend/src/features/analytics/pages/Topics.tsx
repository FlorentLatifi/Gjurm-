import { Link, useParams, useSearchParams } from "react-router-dom";

import { ArticleList } from "@/features/articles";
import { FilterBar } from "@/features/filters";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { isNotFound } from "@/shared/api/client";
import { useTitle } from "@/shared/hooks/useTitle";
import {
  ENTITY_TYPE_LABEL,
  formatChange,
  formatDay,
  formatInt,
  formatPercent,
  formatScore,
  hasComparableHistory,
} from "@/shared/lib/format";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { ErrorState, NotFoundState } from "@/ui/States";
import { DailyLine, SentimentBar } from "@/ui/charts";
import { useApiQuery } from "@/shared/query/apiQuery";
import { topicQueries, topicsQueries } from "../queries";
import { localName, t, tn } from "@/shared/i18n";

export function TopicsPage() {
  useTitle(t("Topics"), t("Which topics dominate Albanian-language news, and how each is trending."));
  const { filters } = useFilters();
  const [search] = useSearchParams();
  const topics = useApiQuery(topicsQueries(search).topics);
  const rows = topics.data ?? [];
  const comparable = hasComparableHistory(rows, (r) => r.articles, (r) => r.previous);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("Topics")}</h1>
          <p>
            {t("Every article gets one primary topic from a fixed list of {n} topics, so counts are comparable over time.", { n: rows.length || 19 })}{" "}
            {comparable
              ? tn(filters.days, "Change compares with the previous {n} day.", "Change compares with the previous {n} days.")
              : t("Change is shown once enough history has been collected.")}
          </p>
        </div>
      </div>
      <FilterBar />
      <Card title={t("Topic ranking")} question={t("Which topics dominate, and which are growing?")} query={topics}
        empty={!rows.some((r) => r.articles)}>
        {() => (
          <div className="table-wrap">
            <table>
              <caption>{tn(filters.days, "Primary topic of analysed articles, last {n} day", "Primary topic of analysed articles, last {n} days")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("Topic")}</th>
                  <th className="num" scope="col">{t("Articles")}</th>
                  <th className="num" scope="col">{t("Share of articles")}</th>
                  <th className="num" scope="col">{t("Change")}</th>
                  <th scope="col" className="col-tone">{t("Tone mix")}</th>
                  <th className="num" scope="col">{t("Mean tone")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.slug}>
                    <td>
                      <Link to={withFilters(`/topics/${r.slug}`, filters)}>{localName(r.name_en, r.name_sq)}</Link>
                    </td>
                    <td className="num">{formatInt(r.articles)}</td>
                    <td className="num">{formatPercent(r.share, 1)}</td>
                    <td className="num">{comparable && (r.articles || r.previous) ? formatChange(r.change) : "—"}</td>
                    <td>
                      <SentimentBar negative={r.negative} positive={r.positive}
                        neutral={Math.max(0, r.articles - r.negative - r.positive)} />
                    </td>
                    <td className="num">{formatScore(r.avg_sentiment)}</td>
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
  const { filters } = useFilters();
  const [search] = useSearchParams();
  const queries = topicQueries(slug, search);
  const topic = useApiQuery(queries.topic);
  const articles = useApiQuery(queries.articles);
  const tp = topic.data?.topic;
  const missing = isNotFound(topic.error);
  const name = tp ? localName(tp.name_en, tp.name_sq) : t("Topic");
  const description = tp ? localName(tp.description, tp.description_sq) : undefined;
  useTitle(missing ? t("Topic not found") : name, description, { index: !missing });
  if (missing) return <NotFoundState title={t("Topic not found")} />;
  if (topic.isError) return <ErrorState error={topic.error} onRetry={() => topic.refetch()} />;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="rank-meta"><Link to={withFilters("/topics", filters)}>{t("Topics")}</Link> /</p>
          <h1>{name}</h1>
          {description && <p>{description}</p>}
        </div>
      </div>
      <FilterBar />
      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title={t("Articles per day")} question={t("How much coverage does this topic get over time?")}
          query={topic} empty={!topic.data?.series.some((d) => d.articles)}
          method={t("Counts articles with this topic as primary or secondary topic.")}
          table={() => (
            <table><caption>{t("Articles per day")}</caption>
              <thead><tr><th scope="col">{t("Day")}</th><th className="num" scope="col">{t("Articles")}</th>
                <th className="num" scope="col">{t("Mean tone")}</th></tr></thead>
              <tbody>{topic.data?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{d.articles}</td>
                  <td className="num">{formatScore(d.avg_sentiment)}</td></tr>))}</tbody>
            </table>
          )}>
          {() => <DailyLine data={topic.data!.series} dataKey="articles" label={t("Articles")} />}
        </Card>
        <Card title={t("Who is involved")} question={t("Which people, organisations and places appear in this topic?")}
          query={topic} empty={!topic.data?.top_entities.length}>
          {() => (
            <RankList unit={(n) => tn(n, "{n} article", "{n} articles")} items={topic.data!.top_entities.slice(0, 10).map((e) => ({
              key: e.id, label: e.name, href: withFilters(`/entities/${e.id}`, filters), value: e.mentions,
              sublabel: ENTITY_TYPE_LABEL[e.type],
            }))} />
          )}
        </Card>
      </div>
      <div className="grid grid--2">
        <Card title={t("By outlet")} question={t("Which outlets cover this topic most, and in what tone?")} query={topic}
          empty={!topic.data?.sources.length}>
          {() => (
            <table>
              <thead><tr><th scope="col">{t("Outlet")}</th><th className="num" scope="col">{t("Articles")}</th>
                <th className="num" scope="col">{t("Mean tone")}</th></tr></thead>
              <tbody>{topic.data!.sources.map((s) => (
                <tr key={s.slug}><td>{s.name}</td><td className="num">{formatInt(s.articles)}</td>
                  <td className="num">{formatScore(s.avg_sentiment)}</td></tr>))}</tbody>
            </table>
          )}
        </Card>
        <Card title={t("Recent articles")} query={articles} empty={!articles.data?.items.length}
          actions={<Link className="btn btn--ghost btn--sm" to={withFilters("/articles", filters, { topic: slug })}>{t("All")}</Link>}>
          {() => <ArticleList items={articles.data!.items} filters={filters} />}
        </Card>
      </div>
    </>
  );
}
