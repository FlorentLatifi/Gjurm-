import { Link } from "react-router-dom";

import { useEntitySpikes, useSentiment, useSentimentShift, useTopicMomentum, useVolume } from "../api/hooks";
import { Card } from "../components/Card";
import { DivergingBars, ToneChart, VolumeChart } from "../components/charts";
import { FilterBar } from "../components/FilterBar";
import { useFilters, withFilters } from "../lib/filters";
import { ENTITY_TYPE_LABEL, formatChange, formatDay, formatInt, formatScore } from "../lib/format";
import { useTitle } from "../lib/useTitle";

export default function TrendsPage() {
  useTitle("Trends", "Accelerating topics, people suddenly in the news and shifts in tone.");
  const { filters, apiParams } = useFilters();
  const momentum = useTopicMomentum();
  const spikes = useEntitySpikes(15);
  const shift = useSentimentShift();
  const volume = useVolume(apiParams);
  const sentiment = useSentiment(apiParams);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Trends</h1>
          <p>What is changing — detected with simple, transparent statistics rather than a black box.</p>
        </div>
      </div>

      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title="Topic momentum" question="Which topics are accelerating this week?"
          query={momentum} method={momentum.data?.method} empty={!momentum.data?.items.length}
          emptyText="Topics need at least 5 articles this week to be ranked."
          table={() => (
            <table>
              <caption>Last 7 days vs previous 7 days</caption>
              <thead><tr><th scope="col">Topic</th><th className="num" scope="col">This week</th>
                <th className="num" scope="col">Previous</th><th className="num" scope="col">Growth</th></tr></thead>
              <tbody>{momentum.data?.items.map((t) => (
                <tr key={t.slug}><td><Link to={`/topics/${t.slug}`}>{t.name_en}</Link></td>
                  <td className="num">{t.current}</td><td className="num">{t.previous}</td>
                  <td className="num">{formatChange(t.growth)}</td></tr>
              ))}</tbody>
            </table>
          )}>
          {() => (
            <DivergingBars
              label="Week-over-week growth per topic; bars right of zero are growing, left are shrinking."
              data={momentum.data!.items.map((t) => ({
                label: t.name_en, value: t.growth ?? 0, detail: `${t.current} vs ${t.previous}`,
              }))}
            />
          )}
        </Card>

        <Card title="People & organisations in the spotlight" question="Who is suddenly mentioned far more than usual?"
          query={spikes} method={spikes.data?.method} empty={!spikes.data?.items.length}
          emptyText="No entity has enough mentions in the last 24 hours.">
          {() => (
            <div className="table-wrap">
              <table>
                <caption>Last 24 hours compared with the previous 28 days</caption>
                <thead><tr><th scope="col">Name</th><th className="num" scope="col">Last 24 h</th>
                  <th className="num" scope="col">Usual per day</th><th className="num" scope="col">z-score</th></tr></thead>
                <tbody>{spikes.data!.items.map((e) => (
                  <tr key={e.id}>
                    <td><Link to={withFilters(`/entities/${e.id}`, filters)}>{e.name}</Link>{" "}
                      <span className="rank-meta">{ENTITY_TYPE_LABEL[e.type]}</span>
                      {e.is_spike && <span className="chip" style={{ marginLeft: 6 }}>Spike</span>}</td>
                    <td className="num">{formatInt(e.last_24h)}</td>
                    <td className="num">{e.baseline_mean?.toFixed(1) ?? "—"}</td>
                    <td className="num">{e.z?.toFixed(1) ?? "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <FilterBar />
      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title="Volume trend" question="Is overall coverage growing?" query={volume} method={volume.data?.method}
          empty={!volume.data?.series.some((d) => d.articles)}>
          {() => <VolumeChart data={volume.data!.series} />}
        </Card>
        <Card title="Tone trend" question="Is coverage becoming more negative or positive?" query={sentiment}
          method={sentiment.data?.method} empty={!sentiment.data?.series.some((d) => d.average !== null)}
          table={() => (
            <table>
              <caption>Mean tone per day (−1 negative … +1 positive)</caption>
              <thead><tr><th scope="col">Day</th><th className="num" scope="col">Mean</th>
                <th className="num" scope="col">7-day mean</th></tr></thead>
              <tbody>{sentiment.data?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{formatScore(d.average)}</td>
                  <td className="num">{formatScore(d.ma7)}</td></tr>
              ))}</tbody>
            </table>
          )}>
          {() => <ToneChart data={sentiment.data!.series} />}
        </Card>
      </div>

      <Card title="Shifts in tone by topic" question="Which topics changed tone most compared with last week?"
        query={shift} method={shift.data?.method} empty={!shift.data?.items.length}
        emptyText="Not enough articles in both weeks to compare.">
        {() => (
          <div className="table-wrap">
            <table>
              <caption>Mean tone, last 7 days vs the 7 days before</caption>
              <thead><tr><th scope="col">Topic</th><th className="num" scope="col">Previous</th>
                <th className="num" scope="col">Now</th><th className="num" scope="col">Change</th>
                <th className="num" scope="col">Articles (now / before)</th></tr></thead>
              <tbody>{shift.data!.items.map((t) => (
                <tr key={t.slug}><td><Link to={`/topics/${t.slug}`}>{t.name_en}</Link></td>
                  <td className="num">{formatScore(t.previous)}</td><td className="num">{formatScore(t.current)}</td>
                  <td className="num"><strong>{formatScore(t.delta)}</strong></td>
                  <td className="num">{t.n_current} / {t.n_previous}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
