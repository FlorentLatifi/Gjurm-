import { Link, useSearchParams } from "react-router-dom";

import { ArticleList } from "@/features/articles";
import { FilterBar } from "@/features/filters";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { useTitle } from "@/shared/hooks/useTitle";
import {
  ENTITY_TYPE_LABEL,
  formatChange,
  formatDay,
  formatDecimal,
  formatInt,
  formatPercent,
  formatScore,
  hasComparableHistory,
  toneLabel,
} from "@/shared/lib/format";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { StatTile } from "@/ui/StatTile";
import { SentimentMixChart, VolumeChart } from "@/ui/charts";
import { useApiQuery } from "@/shared/query/apiQuery";
import { overviewQueries } from "../queries";
import { localName, t, tn } from "@/shared/i18n";

export default function OverviewPage() {
  useTitle(t("Dashboard"), t("What Albanian and Balkan media are reporting right now: topics, people, tone."));
  const { filters } = useFilters();
  const [search] = useSearchParams();
  const queries = overviewQueries(search);
  const overview = useApiQuery(queries.overview);
  const volume = useApiQuery(queries.volume);
  const sentiment = useApiQuery(queries.sentiment);
  const topics = useApiQuery(queries.topics);
  const momentum = useApiQuery(queries.momentum);
  const spikes = useApiQuery(queries.spikes);
  const latest = useApiQuery(queries.latest);
  const o = overview.data;
  const loading = overview.isPending;
  const dayDelta = o && o.yesterday > 0 ? (o.today - o.yesterday) / o.yesterday : null;
  const rangeText = o ? `${formatDay(o.range.start)} – ${formatDay(o.range.end)}` : "";
  const topicRows = topics.data ?? [];
  const comparable = hasComparableHistory(topicRows, (r) => r.articles, (r) => r.previous);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("What the news is talking about")}</h1>
          <p>
            {t("Albanian-language and regional outlets, read every 15 minutes and analysed by AI.")}
            {rangeText && <> {t("Showing {range}.", { range: rangeText })}</>}
          </p>
        </div>
      </div>
      <FilterBar />

      <div className="grid grid--kpi" style={{ marginBottom: 14 }}>
        <StatTile label={t("Articles today")} value={formatInt(o?.today)} loading={loading}
          delta={dayDelta} deltaLabel={t("vs yesterday")} upIsGood={null} />
        <StatTile label={tn(filters.days, "Articles, last {n} day", "Articles, last {n} days")} value={formatInt(o?.articles)}
          loading={loading} sub={o ? tn(o.sources, "{n} outlet", "{n} outlets") : undefined} />
        <StatTile label={t("Distinct stories")} value={formatInt(o?.unique_stories)} loading={loading}
          sub={o && o.articles ? t("{share} of articles repeat a story another outlet ran", { share: formatPercent(1 - o.unique_stories / o.articles) }) : undefined} />
        <StatTile label={t("Top topic")} textValue value={o?.top_topic ? localName(o.top_topic.name_en, o.top_topic.name_sq) : "—"} loading={loading}
          sub={o?.top_topic ? t("{share} of analysed articles", { share: formatPercent(o.top_topic.share) }) : undefined} />
        <StatTile label={t("Most mentioned")} textValue value={o?.top_entity?.name ?? "—"} loading={loading}
          sub={o?.top_entity ? `${ENTITY_TYPE_LABEL[o.top_entity.type]} · ${tn(o.top_entity.mentions, "{n} article", "{n} articles")}` : undefined} />
        <StatTile label={t("Overall tone")} value={formatScore(o?.sentiment.average)} loading={loading}
          sub={o ? t("{tone} on a −1…+1 scale", { tone: toneLabel(o.sentiment.average) }) : undefined} />
      </div>

      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title={t("Publishing volume")} question={t("Is coverage rising or falling?")}
          query={volume} empty={!volume.data?.series.some((d) => d.articles > 0)}
          method={volume.data && localName(volume.data.method, volume.data.method_sq)}
          table={() => (
            <table>
              <caption>{t("Articles per day")}</caption>
              <thead><tr><th scope="col">{t("Day")}</th><th className="num" scope="col">{t("Articles")}</th>
                <th className="num" scope="col">{t("Stories")}</th><th className="num" scope="col">{t("7-day avg")}</th></tr></thead>
              <tbody>{volume.data?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{formatInt(d.articles)}</td>
                  <td className="num">{formatInt(d.stories)}</td><td className="num">{d.ma7 === null ? "—" : formatDecimal(d.ma7)}</td></tr>
              ))}</tbody>
            </table>
          )}>
          {() => <VolumeChart data={volume.data!.series} />}
        </Card>

        <Card title={t("Trending now")} question={t("Which people, organisations and topics are suddenly in the news?")}
          query={spikes} method={spikes.data && localName(spikes.data.method, spikes.data.method_sq)}
          empty={!spikes.data?.items.length && !momentum.data?.items.length}
          emptyText={t("Not enough history yet to detect trends.")}>
          {() => (
            <div className="stack">
              <RankList unit={(n) => tn(n, "{n} mention (24 h)", "{n} mentions (24 h)")} items={(spikes.data?.items ?? []).slice(0, 5).map((e) => ({
                key: e.id, label: e.name, href: withFilters(`/entities/${e.id}`, filters), value: e.last_24h,
                sublabel: ENTITY_TYPE_LABEL[e.type],
                meta: e.is_spike ? <strong className="ink"> · {t("spike z={z}", { z: e.z === null ? "—" : formatDecimal(e.z) })}</strong> : null,
              }))} />
              {momentum.data && momentum.data.items.length > 0 && (
                <p className="card__question">
                  {t("Fastest-growing topic this week:")}{" "}
                  <Link to={withFilters(`/topics/${momentum.data.items[0]!.slug}`, filters)}>
                    {localName(momentum.data.items[0]!.name_en, momentum.data.items[0]!.name_sq)}
                  </Link>{" "}
                  ({t("{change} vs previous week", { change: formatChange(momentum.data.items[0]!.growth) })}).{" "}
                  <Link to="/trends">{t("All trends")} →</Link>
                </p>
              )}
            </div>
          )}
        </Card>
      </div>

      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title={t("Topics")} question={t("Which topics dominate coverage?")} query={topics}
          empty={!topics.data?.some((r) => r.articles > 0)}
          method={comparable ? tn(filters.days, "Change compares with the previous {n} day.", "Change compares with the previous {n} days.")
            : tn(filters.days, "Not enough history yet to compare with the previous {n} day.", "Not enough history yet to compare with the previous {n} days.")}
          actions={<Link className="btn btn--ghost btn--sm" to={withFilters("/topics", filters)}>{t("All topics")}</Link>}>
          {() => (
            <RankList unit={(n) => tn(n, "{n} article", "{n} articles")} items={(topics.data ?? []).filter((r) => r.articles > 0).slice(0, 8).map((r) => ({
              key: r.slug, label: localName(r.name_en, r.name_sq), href: withFilters(`/topics/${r.slug}`, filters), value: r.articles,
              meta: comparable ? <> · {formatChange(r.change)}</> : null,
            }))} />
          )}
        </Card>
        <Card title={t("Tone of coverage")} question={t("How much of the news is negative, neutral or positive?")}
          query={sentiment} empty={!sentiment.data?.series.some((d) => d.negative + d.neutral + d.positive > 0)}
          method={t("Tone is judged by the AI for each article (see Methodology). Share of articles per day.")}
          table={() => (
            <table>
              <caption>{t("Articles by tone per day")}</caption>
              <thead><tr><th scope="col">{t("Day")}</th><th className="num" scope="col">{t("Negative")}</th>
                <th className="num" scope="col">{t("Neutral")}</th><th className="num" scope="col">{t("Positive")}</th></tr></thead>
              <tbody>{sentiment.data?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{d.negative}</td>
                  <td className="num">{d.neutral}</td><td className="num">{d.positive}</td></tr>
              ))}</tbody>
            </table>
          )}>
          {() => <SentimentMixChart data={sentiment.data!.series} />}
        </Card>
      </div>

      <Card title={t("Latest articles")} question={t("The newest items, linked to their original publishers.")}
        query={latest} empty={!latest.data?.items.length}
        actions={<Link className="btn btn--ghost btn--sm" to={withFilters("/articles", filters)}>{t("Search articles")}</Link>}>
        {() => <ArticleList items={latest.data!.items} filters={filters} />}
      </Card>
    </>
  );
}
