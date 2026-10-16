import { Link, useSearchParams } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { useTitle } from "@/shared/hooks/useTitle";
import { ENTITY_TYPE_LABEL, formatChange, formatDay, formatDecimal, formatInt, formatScore } from "@/shared/lib/format";
import { Card } from "@/ui/Card";
import { DivergingBars, ToneChart, VolumeChart } from "@/ui/charts";
import { useApiQuery } from "@/shared/query/apiQuery";
import { trendsQueries } from "../queries";
import { localName, t } from "@/shared/i18n";

export default function TrendsPage() {
  useTitle(t("Trends"), t("Accelerating topics, people suddenly in the news and shifts in tone."));
  const { filters } = useFilters();
  const [search] = useSearchParams();
  const queries = trendsQueries(search);
  const momentum = useApiQuery(queries.momentum);
  const spikes = useApiQuery(queries.spikes);
  const shift = useApiQuery(queries.shift);
  const volume = useApiQuery(queries.volume);
  const sentiment = useApiQuery(queries.sentiment);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("Trends")}</h1>
          <p>{t("What is changing — detected with simple, transparent statistics rather than a black box.")}</p>
        </div>
      </div>

      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title={t("Topic momentum")} question={t("Which topics are accelerating this week?")}
          query={momentum} method={momentum.data && localName(momentum.data.method, momentum.data.method_sq)} empty={!momentum.data?.items.length}
          emptyText={t("Topics need at least 5 articles this week to be ranked.")}
          table={() => (
            <table>
              <caption>{t("Last 7 days vs previous 7 days")}</caption>
              <thead><tr><th scope="col">{t("Topic")}</th><th className="num" scope="col">{t("This week")}</th>
                <th className="num" scope="col">{t("Previous")}</th><th className="num" scope="col">{t("Growth")}</th></tr></thead>
              <tbody>{momentum.data?.items.map((r) => (
                <tr key={r.slug}><td><Link to={`/topics/${r.slug}`}>{localName(r.name_en, r.name_sq)}</Link></td>
                  <td className="num">{r.current}</td><td className="num">{r.previous}</td>
                  <td className="num">{formatChange(r.growth)}</td></tr>
              ))}</tbody>
            </table>
          )}>
          {() => (
            <DivergingBars
              label={t("Week-over-week growth per topic; bars right of zero are growing, left are shrinking.")}
              data={momentum.data!.items.map((r) => ({
                label: localName(r.name_en, r.name_sq), value: r.growth ?? 0, detail: t("{current} vs {previous}", { current: r.current, previous: r.previous }),
              }))}
            />
          )}
        </Card>

        <Card title={t("People & organisations in the spotlight")} question={t("Who is suddenly mentioned far more than usual?")}
          query={spikes} method={spikes.data && localName(spikes.data.method, spikes.data.method_sq)} empty={!spikes.data?.items.length}
          emptyText={t("No name has enough mentions in the last 24 hours.")}>
          {() => (
            <div className="table-wrap">
              <table>
                <caption>{t("Last 24 hours compared with the previous 28 days")}</caption>
                <thead><tr><th scope="col">{t("Name")}</th><th className="num" scope="col">{t("Last 24 h")}</th>
                  <th className="num" scope="col">{t("Usual per day")}</th><th className="num" scope="col">{t("z-score")}</th></tr></thead>
                <tbody>{spikes.data!.items.map((e) => (
                  <tr key={e.id}>
                    <td><Link to={withFilters(`/entities/${e.id}`, filters)}>{e.name}</Link>{" "}
                      <span className="rank-meta">{ENTITY_TYPE_LABEL[e.type]}</span>
                      {e.is_spike && <> <span className="chip">{t("Spike")}</span></>}</td>
                    <td className="num">{formatInt(e.last_24h)}</td>
                    <td className="num">{e.baseline_mean === null ? "—" : formatDecimal(e.baseline_mean)}</td>
                    <td className="num">{e.z === null ? "—" : formatDecimal(e.z)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <FilterBar />
      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title={t("Volume trend")} question={t("Is overall coverage growing?")} query={volume} method={volume.data && localName(volume.data.method, volume.data.method_sq)}
          empty={!volume.data?.series.some((d) => d.articles)}>
          {() => <VolumeChart data={volume.data!.series} />}
        </Card>
        <Card title={t("Tone trend")} question={t("Is coverage becoming more negative or positive?")} query={sentiment}
          method={sentiment.data && localName(sentiment.data.method, sentiment.data.method_sq)} empty={!sentiment.data?.series.some((d) => d.average !== null)}
          table={() => (
            <table>
              <caption>{t("Mean tone per day (−1 negative … +1 positive)")}</caption>
              <thead><tr><th scope="col">{t("Day")}</th><th className="num" scope="col">{t("Mean")}</th>
                <th className="num" scope="col">{t("7-day mean")}</th></tr></thead>
              <tbody>{sentiment.data?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{formatScore(d.average)}</td>
                  <td className="num">{formatScore(d.ma7)}</td></tr>
              ))}</tbody>
            </table>
          )}>
          {() => <ToneChart data={sentiment.data!.series} />}
        </Card>
      </div>

      <Card title={t("Shifts in tone by topic")} question={t("Which topics changed tone most compared with last week?")}
        query={shift} method={shift.data && localName(shift.data.method, shift.data.method_sq)} empty={!shift.data?.items.length}
        emptyText={t("Not enough articles in both weeks to compare.")}>
        {() => (
          <div className="table-wrap">
            <table>
              <caption>{t("Mean tone, last 7 days vs the 7 days before")}</caption>
              <thead><tr><th scope="col">{t("Topic")}</th><th className="num" scope="col">{t("Previous")}</th>
                <th className="num" scope="col">{t("Now")}</th><th className="num" scope="col">{t("Change")}</th>
                <th className="num" scope="col">{t("Articles (now / before)")}</th></tr></thead>
              <tbody>{shift.data!.items.map((r) => (
                <tr key={r.slug}><td><Link to={`/topics/${r.slug}`}>{localName(r.name_en, r.name_sq)}</Link></td>
                  <td className="num">{formatScore(r.previous)}</td><td className="num">{formatScore(r.current)}</td>
                  <td className="num"><strong>{formatScore(r.delta)}</strong></td>
                  <td className="num">{r.n_current} / {r.n_previous}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
