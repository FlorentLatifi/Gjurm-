import { Link, useSearchParams } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { useTitle } from "@/shared/hooks/useTitle";
import { formatDateTime, formatDecimal, formatInt, formatPercent, formatScore } from "@/shared/lib/format";
import {
  BIAS_GROUP_COLOR,
  BIAS_LABEL,
  biasGroup,
  countryLabel,
  FACTUALITY_LABEL,
  OWNERSHIP_LABEL,
} from "@/shared/model/ratings";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { SentimentBar } from "@/ui/charts";
import { useApiQuery } from "@/shared/query/apiQuery";
import { sourcesQueries } from "../queries";
import { localName, t, tn } from "@/shared/i18n";

export default function SourcesPage() {
  useTitle(t("Sources"), t("How Albanian-language outlets differ in volume, topics and tone."));
  const { filters } = useFilters();
  const [search] = useSearchParams();
  const sources = useApiQuery(sourcesQueries(search).sources);
  const rows = sources.data ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("Sources")}</h1>
          <p>{t("How outlets differ, and how they are rated. “Original” is the share of an outlet’s articles that were not a near-verbatim copy of a headline already published elsewhere; “First” counts the stories several outlets covered that this one published first.")}{" "}
            <Link to="/about#ratings">{t("How outlets are rated")}</Link></p>
        </div>
      </div>
      <FilterBar showSources={false} />
      <div className="stack">
        <Card title={t("Volume by outlet")} question={t("Who publishes the most?")} query={sources}
          empty={!rows.some((s) => s.articles)}>
          {() => (
            <RankList unit={(n) => tn(n, "{n} article", "{n} articles")} items={rows.filter((s) => s.articles).map((s) => ({
              key: s.slug, label: s.name, value: s.articles, href: withFilters(`/sources/${s.slug}`, filters),
              meta: <> · {t("{n}/day", { n: s.per_day === null ? "—" : formatDecimal(s.per_day) })}</>,
            }))} />
          )}
        </Card>
        <Card title={t("Who breaks the news")} question={t("Stories covered by two or more outlets: who published first?")}
          query={sources} empty={!rows.some((s) => s.first_reports)}
          emptyText={t("No story was covered by two or more outlets in this period yet.")}>
          {() => (
            <RankList unit={(n) => tn(n, "{n} first report", "{n} first reports")} items={rows.filter((s) => s.first_reports).sort((a, b) => b.first_reports - a.first_reports).map((s) => ({
              key: s.slug, label: s.name, value: s.first_reports, href: withFilters(`/sources/${s.slug}`, filters),
              meta: <> · {tn(s.stories, "{n} story covered", "{n} stories covered")}</>,
            }))} />
          )}
        </Card>
        <Card title={t("Outlet profiles")} question={t("How do outlets differ in ratings, originality, tone and topic focus?")}
          query={sources} empty={!rows.length}>
          {() => (
            <div className="table-wrap">
              <table>
                <caption>{tn(filters.days, "Last {n} day", "Last {n} days")}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t("Outlet")}</th>
                    <th scope="col">{t("Perspective")}</th>
                    <th scope="col">{t("Factuality")}</th>
                    <th scope="col">{t("Ownership")}</th>
                    <th className="num" scope="col">{t("Articles")}</th>
                    <th className="num" scope="col">{t("Stories")}</th>
                    <th className="num" scope="col">{t("First")}</th>
                    <th className="num" scope="col">{t("Original")}</th>
                    <th scope="col" className="col-tone">{t("Tone mix")}</th>
                    <th className="num" scope="col">{t("Mean tone")}</th>
                    <th scope="col">{t("Top topics")}</th>
                    <th scope="col">{t("Feed")}</th>
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
                        <span className="chips">
                          {s.top_topics.slice(0, 3).map((tp) => (
                            <Link key={tp.slug} className="chip" to={withFilters(`/topics/${tp.slug}`, { ...filters, sources: [s.slug] })}>
                              {localName(tp.name_en, tp.name_sq)}
                            </Link>
                          ))}
                        </span>
                      </td>
                      <td className="rank-meta">
                        {s.is_active ? (s.consecutive_failures ? t("retrying ({n})", { n: s.consecutive_failures }) : t("active"))
                          : t("paused")}
                        <div>{s.last_success_at ? t("ok {time}", { time: formatDateTime(s.last_success_at) }) : ""}</div>
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
