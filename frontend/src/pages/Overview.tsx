import { Link } from "react-router-dom";

import {
  useArticles,
  useEntitySpikes,
  useOverview,
  useSentiment,
  useTopicMomentum,
  useTopics,
  useVolume,
} from "../api/hooks";
import { Card } from "../components/Card";
import { SentimentMixChart, VolumeChart } from "../components/charts";
import { FilterBar } from "../components/FilterBar";
import { ArticleList, RankList } from "../components/lists";
import { StatTile } from "../components/StatTile";
import { useFilters, withFilters } from "../lib/filters";
import {
  ENTITY_TYPE_LABEL,
  formatChange,
  formatDay,
  formatInt,
  formatPercent,
  formatScore,
  hasComparableHistory,
  toneLabel,
} from "../lib/format";
import { useTitle } from "../lib/useTitle";

export default function OverviewPage() {
  useTitle("", "What Albanian and Balkan media are reporting right now: topics, people, tone.");
  const { filters, apiParams } = useFilters();
  const overview = useOverview(apiParams);
  const volume = useVolume(apiParams);
  const sentiment = useSentiment(apiParams);
  const topics = useTopics(apiParams);
  const momentum = useTopicMomentum();
  const spikes = useEntitySpikes(6);
  const latest = useArticles({ ...apiParams, page_size: 8 });
  const o = overview.data;
  const loading = overview.isPending;
  const dayDelta = o && o.yesterday > 0 ? (o.today - o.yesterday) / o.yesterday : null;
  const rangeText = o ? `${formatDay(o.range.start)} – ${formatDay(o.range.end)}` : "";
  const topicRows = topics.data ?? [];
  const comparable = hasComparableHistory(topicRows, (t) => t.articles, (t) => t.previous);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>What the news is talking about</h1>
          <p>
            Albanian-language and regional outlets, read every 15 minutes and analysed by AI.
            {rangeText && <> Showing {rangeText}.</>}
          </p>
        </div>
      </div>
      <FilterBar />

      <div className="grid grid--kpi" style={{ marginBottom: 14 }}>
        <StatTile label="Articles today" value={formatInt(o?.today)} loading={loading}
          delta={dayDelta} deltaLabel="vs yesterday" upIsGood={null} />
        <StatTile label={`Articles, last ${filters.days} days`} value={formatInt(o?.articles)}
          loading={loading} sub={o ? `${formatInt(o.sources)} outlets` : undefined} />
        <StatTile label="Distinct stories" value={formatInt(o?.unique_stories)} loading={loading}
          sub={o && o.articles ? `${formatPercent(1 - o.unique_stories / o.articles)} of articles repeat a story another outlet ran` : undefined} />
        <StatTile label="Top topic" textValue value={o?.top_topic?.name_en ?? "—"} loading={loading}
          sub={o?.top_topic ? `${formatPercent(o.top_topic.share)} of analysed articles` : undefined} />
        <StatTile label="Most mentioned" textValue value={o?.top_entity?.name ?? "—"} loading={loading}
          sub={o?.top_entity ? `${ENTITY_TYPE_LABEL[o.top_entity.type]} · ${formatInt(o.top_entity.mentions)} articles` : undefined} />
        <StatTile label="Overall tone" value={formatScore(o?.sentiment.average)} loading={loading}
          sub={o ? `${toneLabel(o.sentiment.average)} on a −1…+1 scale` : undefined} />
      </div>

      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title="Publishing volume" question="Is coverage rising or falling?"
          query={volume} empty={!volume.data?.series.some((d) => d.articles > 0)} method={volume.data?.method}
          table={() => (
            <table>
              <caption>Articles per day</caption>
              <thead><tr><th scope="col">Day</th><th className="num" scope="col">Articles</th>
                <th className="num" scope="col">Stories</th><th className="num" scope="col">7-day avg</th></tr></thead>
              <tbody>{volume.data?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{formatInt(d.articles)}</td>
                  <td className="num">{formatInt(d.stories)}</td><td className="num">{d.ma7?.toFixed(1) ?? "—"}</td></tr>
              ))}</tbody>
            </table>
          )}>
          {() => <VolumeChart data={volume.data!.series} />}
        </Card>

        <Card title="Trending now" question="Which people, organisations and topics are suddenly in the news?"
          query={spikes} method={spikes.data?.method}
          empty={!spikes.data?.items.length && !momentum.data?.items.length}
          emptyText="Not enough history yet to detect trends.">
          {() => (
            <div className="stack">
              <RankList unit="mentions (24 h)" items={(spikes.data?.items ?? []).slice(0, 5).map((e) => ({
                key: e.id, label: e.name, href: withFilters(`/entities/${e.id}`, filters), value: e.last_24h,
                sublabel: ENTITY_TYPE_LABEL[e.type],
                meta: e.is_spike ? <strong style={{ color: "var(--ink)" }}> · spike z={e.z?.toFixed(1)}</strong> : null,
              }))} />
              {momentum.data && momentum.data.items.length > 0 && (
                <p className="card__question">
                  Fastest-growing topic this week:{" "}
                  <Link to={withFilters(`/topics/${momentum.data.items[0]!.slug}`, filters)}>
                    {momentum.data.items[0]!.name_en}
                  </Link>{" "}
                  ({formatChange(momentum.data.items[0]!.growth)} vs previous week).{" "}
                  <Link to="/trends">All trends →</Link>
                </p>
              )}
            </div>
          )}
        </Card>
      </div>

      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title="Topics" question="Which topics dominate coverage?" query={topics}
          empty={!topics.data?.some((t) => t.articles > 0)}
          method={comparable ? `Change compares with the previous ${filters.days} days.`
            : `Not enough history yet to compare with the previous ${filters.days} days.`}
          actions={<Link className="btn btn--ghost btn--sm" to={withFilters("/topics", filters)}>All topics</Link>}>
          {() => (
            <RankList unit="articles" items={(topics.data ?? []).filter((t) => t.articles > 0).slice(0, 8).map((t) => ({
              key: t.slug, label: t.name_en, href: withFilters(`/topics/${t.slug}`, filters), value: t.articles,
              meta: comparable ? <> · {formatChange(t.change)}</> : null,
            }))} />
          )}
        </Card>
        <Card title="Tone of coverage" question="How much of the news is negative, neutral or positive?"
          query={sentiment} empty={!sentiment.data?.series.some((d) => d.negative + d.neutral + d.positive > 0)}
          method="Tone is judged by the AI for each article (see Methodology). Share of articles per day."
          table={() => (
            <table>
              <caption>Articles by tone per day</caption>
              <thead><tr><th scope="col">Day</th><th className="num" scope="col">Negative</th>
                <th className="num" scope="col">Neutral</th><th className="num" scope="col">Positive</th></tr></thead>
              <tbody>{sentiment.data?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{d.negative}</td>
                  <td className="num">{d.neutral}</td><td className="num">{d.positive}</td></tr>
              ))}</tbody>
            </table>
          )}>
          {() => <SentimentMixChart data={sentiment.data!.series} />}
        </Card>
      </div>

      <Card title="Latest articles" question="The newest items, linked to their original publishers."
        query={latest} empty={!latest.data?.items.length}
        actions={<Link className="btn btn--ghost btn--sm" to={withFilters("/articles", filters)}>Search articles</Link>}>
        {() => <ArticleList items={latest.data!.items} />}
      </Card>
    </>
  );
}
