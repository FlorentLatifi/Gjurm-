import { useId } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ArticleList } from "@/features/articles";
import { FilterBar } from "@/features/filters";
import type { EntityType } from "@/shared/api/types";
import { useFilters, withFilters } from "@/shared/hooks/useFilters";
import { isNotFound } from "@/shared/api/client";
import { useTitle } from "@/shared/hooks/useTitle";
import {
  ENTITY_TYPE_LABEL,
  formatChange,
  formatDay,
  formatInt,
  formatScore,
  hasComparableHistory,
} from "@/shared/lib/format";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { SearchField } from "@/ui/SearchField";
import { ErrorState, NotFoundState } from "@/ui/States";
import { DailyLine } from "@/ui/charts";
import { useApiQuery } from "@/shared/query/apiQuery";
import { entitiesQueries, entitiesState, entityQueries } from "../queries";
import { isPositiveId } from "@/shared/lib/ids";
import { labels, localName, t, tn } from "@/shared/i18n";

const TYPE_LABEL = labels({ all: "All", person: "People", organization: "Organisations", location: "Places" });
const TYPES: { value: EntityType | ""; label: keyof typeof TYPE_LABEL }[] = [
  { value: "", label: "all" },
  { value: "person", label: "person" },
  { value: "organization", label: "organization" },
  { value: "location", label: "location" },
];

export function EntitiesPage() {
  useTitle(t("People & organisations"), t("Who and what is most discussed in Albanian-language news."));
  const { filters } = useFilters();
  const [params, setParams] = useSearchParams();
  const { type, q } = entitiesState(params);
  const searchId = useId();
  const queries = entitiesQueries(params);
  const entities = useApiQuery(queries.entities);
  const pairs = useApiQuery(queries.pairs);
  const comparable = hasComparableHistory(entities.data ?? [], (e) => e.mentions, (e) => e.previous);

  const set = (key: "type" | "q", value: string) =>
    setParams((prev) => {
      const out = new URLSearchParams(prev);
      if (value) out.set(key, value);
      else out.delete(key);
      return out;
    }, { replace: true });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("People, organisations & places")}</h1>
          <p>{t("Names extracted by the AI and checked against the headline text (names the text does not contain are discarded).")}</p>
        </div>
      </div>
      <FilterBar />
      <div className="filters">
        <div className="segmented" role="group" aria-label={t("Kind of name")}>
          {TYPES.map((k) => (
            <button key={k.value} type="button" aria-pressed={type === k.value} onClick={() => set("type", k.value)}>
              {TYPE_LABEL[k.label]}
            </button>
          ))}
        </div>
        <SearchField id={searchId} label={t("Search names")} hideLabel value={q} onCommit={(v) => set("q", v)}
          placeholder={t("Search a name, e.g. Kurti, Prishtina…")} maxLength={80} delay={300} />
      </div>
      <div className="grid grid--2">
        <Card title={t("Most mentioned")} question={t("Who and what is most discussed?")} query={entities}
          empty={!entities.data?.length} emptyText={q ? t("No names match your search.") : t("No names in this period.")}>
          {() => (
            <div className="table-wrap">
              <table>
                <caption>{tn(filters.days, "Number of articles mentioning each name, last {n} day", "Number of articles mentioning each name, last {n} days")}</caption>
                <thead><tr><th scope="col">{t("Name")}</th><th className="num" scope="col">{t("Articles")}</th>
                  <th className="num" scope="col">{t("Change")}</th><th className="num" scope="col">{t("Mean tone")}</th>
                  <th className="num" scope="col">{t("Outlets")}</th></tr></thead>
                <tbody>{entities.data!.map((e) => (
                  <tr key={e.id}>
                    <td><Link to={withFilters(`/entities/${e.id}`, filters)}>{e.name}</Link>
                      <div className="rank-meta">{ENTITY_TYPE_LABEL[e.type]}</div></td>
                    <td className="num">{formatInt(e.mentions)}</td>
                    <td className="num">{comparable ? formatChange(e.change) : "—"}</td>
                    <td className="num">{formatScore(e.avg_sentiment)}</td>
                    <td className="num">{e.sources}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title={t("Mentioned together")} question={t("Which names appear in the same articles most often?")}
          query={pairs} empty={!pairs.data?.length}>
          {() => (
            <RankList unit={(n) => tn(n, "{n} shared article", "{n} shared articles")} items={pairs.data!.slice(0, 12).map((p) => ({
              key: `${p.a_id}-${p.b_id}`, label: `${p.a_name} + ${p.b_name}`,
              href: withFilters(`/entities/${p.a_id}`, filters), value: p.together,
            }))} />
          )}
        </Card>
      </div>
    </>
  );
}

export function EntityPage() {
  const id = Number(useParams().id);
  const { filters } = useFilters();
  const [search] = useSearchParams();
  const queries = entityQueries(id, search);
  const valid = isPositiveId(id);
  const entity = useApiQuery(queries.entity, valid);
  const articles = useApiQuery(queries.articles, valid);
  const e = entity.data;
  const missing = !valid || isNotFound(entity.error);
  useTitle(missing ? t("Not found") : (e?.entity.name ?? t("Name")), undefined, { index: !missing });
  if (missing) return <NotFoundState title={t("Not found")}>{t("No person, organisation or place has this address.")}</NotFoundState>;
  if (entity.isError) return <ErrorState error={entity.error} onRetry={() => entity.refetch()} />;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="rank-meta"><Link to={withFilters("/entities", filters)}>{t("People & organisations")}</Link> /</p>
          <h1>{e?.entity.name ?? "…"}</h1>
          {e && (
            <p>{ENTITY_TYPE_LABEL[e.entity.type]} · {tn(e.mentions, "{n} article", "{n} articles")}{" "}
              {tn(filters.days, "in the last {n} day", "in the last {n} days")} · {t("mean tone {score}", { score: formatScore(e.avg_sentiment) })}</p>
          )}
        </div>
      </div>
      <FilterBar />
      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title={t("Mentions per day")} question={t("When was this name in the news?")} query={entity}
          empty={!e?.mentions}
          table={() => (
            <table><caption>{t("Articles mentioning this name per day")}</caption>
              <thead><tr><th scope="col">{t("Day")}</th><th className="num" scope="col">{t("Articles")}</th>
                <th className="num" scope="col">{t("Mean tone")}</th></tr></thead>
              <tbody>{e?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{d.mentions}</td>
                  <td className="num">{formatScore(d.avg_sentiment)}</td></tr>))}</tbody>
            </table>
          )}>
          {() => <DailyLine data={e!.series} dataKey="mentions" label={t("Articles")} />}
        </Card>
        <Card title={t("Mentioned alongside")} question={t("Who else appears in the same articles?")} query={entity}
          empty={!e?.co_mentions.length}>
          {() => (
            <RankList unit={(n) => tn(n, "{n} shared article", "{n} shared articles")} items={e!.co_mentions.map((c) => ({
              key: c.id, label: c.name, href: withFilters(`/entities/${c.id}`, filters), value: c.together,
              sublabel: ENTITY_TYPE_LABEL[c.type],
            }))} />
          )}
        </Card>
      </div>
      <div className="grid grid--2">
        <div className="stack">
          <Card title={t("In which topics")} query={entity} empty={!e?.topics.length}>
            {() => (
              <RankList unit={(n) => tn(n, "{n} article", "{n} articles")} items={e!.topics.map((tp) => ({
                key: tp.slug, label: localName(tp.name_en, tp.name_sq), href: withFilters(`/topics/${tp.slug}`, filters), value: tp.articles,
              }))} />
            )}
          </Card>
          <Card title={t("By outlet")} question={t("Who covers this name, and in what tone?")} query={entity}
            empty={!e?.sources.length}>
            {() => (
              <table>
                <thead><tr><th scope="col">{t("Outlet")}</th><th className="num" scope="col">{t("Articles")}</th>
                  <th className="num" scope="col">{t("Mean tone")}</th></tr></thead>
                <tbody>{e!.sources.map((s) => (
                  <tr key={s.slug}><td>{s.name}</td><td className="num">{s.articles}</td>
                    <td className="num">{formatScore(s.avg_sentiment)}</td></tr>))}</tbody>
              </table>
            )}
          </Card>
        </div>
        <Card title={t("Articles")} query={articles} empty={!articles.data?.items.length}
          actions={<Link className="btn btn--ghost btn--sm" to={withFilters("/articles", filters, { entity: String(id) })}>{t("All")}</Link>}>
          {() => <ArticleList items={articles.data!.items} filters={filters} />}
        </Card>
      </div>
    </>
  );
}
