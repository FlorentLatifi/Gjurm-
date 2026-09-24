import { useEffect, useId, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useArticles, useCoOccurrence, useEntities, useEntity } from "../api/hooks";
import type { EntityType } from "../api/types";
import { Card } from "../components/Card";
import { DailyLine } from "../components/charts";
import { FilterBar } from "../components/FilterBar";
import { ArticleList, RankList } from "../components/lists";
import { ErrorState } from "../components/States";
import { useFilters, withFilters } from "../lib/filters";
import {
  ENTITY_TYPE_LABEL,
  formatChange,
  formatDay,
  formatInt,
  formatScore,
  hasComparableHistory,
} from "../lib/format";
import { useTitle } from "../lib/useTitle";

const TYPES: { value: EntityType | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "person", label: "People" },
  { value: "organization", label: "Organisations" },
  { value: "location", label: "Places" },
];

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

export function EntitiesPage() {
  useTitle("People & organisations", "Who and what is most discussed in Albanian-language news.");
  const { filters, apiParams } = useFilters();
  const [params, setParams] = useSearchParams();
  const type = (params.get("type") ?? "") as EntityType | "";
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search.trim());
  const searchId = useId();
  const entities = useEntities({ ...apiParams, type: type || undefined, q: q.length >= 2 ? q : undefined, limit: 30 });
  const pairs = useCoOccurrence(apiParams);
  const comparable = hasComparableHistory(entities.data ?? [], (e) => e.mentions, (e) => e.previous);

  const setType = (value: string) =>
    setParams((prev) => {
      const out = new URLSearchParams(prev);
      if (value) out.set("type", value);
      else out.delete("type");
      return out;
    }, { replace: true });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>People, organisations &amp; places</h1>
          <p>Named entities extracted by the AI and checked against the headline text (names the text
            does not contain are discarded).</p>
        </div>
      </div>
      <FilterBar />
      <div className="filters">
        <div className="segmented" role="group" aria-label="Entity type">
          {TYPES.map((t) => (
            <button key={t.value} type="button" aria-pressed={type === t.value} onClick={() => setType(t.value)}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="field field--grow">
          <label htmlFor={searchId} className="visually-hidden">Search names</label>
          <input id={searchId} type="search" placeholder="Search a name, e.g. Kurti, Prishtina…" value={search}
            onChange={(e) => setSearch(e.target.value)} maxLength={80} />
        </div>
      </div>
      <div className="grid grid--2">
        <Card title="Most mentioned" question="Who and what is most discussed?" query={entities}
          empty={!entities.data?.length} emptyText={q ? "No names match your search." : "No entities in this period."}>
          {() => (
            <div className="table-wrap">
              <table>
                <caption>Number of articles mentioning each entity, last {filters.days} days</caption>
                <thead><tr><th scope="col">Name</th><th className="num" scope="col">Articles</th>
                  <th className="num" scope="col">Change</th><th className="num" scope="col">Mean tone</th>
                  <th className="num" scope="col">Outlets</th></tr></thead>
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
        <Card title="Mentioned together" question="Which names appear in the same articles most often?"
          query={pairs} empty={!pairs.data?.length}>
          {() => (
            <RankList unit="shared articles" items={pairs.data!.slice(0, 12).map((p) => ({
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
  const { filters, apiParams } = useFilters();
  const entity = useEntity(id, apiParams);
  const articles = useArticles({ ...apiParams, entity: id, page_size: 10 });
  const e = entity.data;
  useTitle(e?.entity.name ?? "Entity");
  if (entity.isError) return <ErrorState error={entity.error} onRetry={() => entity.refetch()} />;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="rank-meta"><Link to={withFilters("/entities", filters)}>People &amp; organisations</Link> /</p>
          <h1>{e?.entity.name ?? "…"}</h1>
          {e && (
            <p>{ENTITY_TYPE_LABEL[e.entity.type]} · {formatInt(e.mentions)} articles in the last {filters.days} days ·
              mean tone {formatScore(e.avg_sentiment)}</p>
          )}
        </div>
      </div>
      <FilterBar />
      <div className="grid grid--2" style={{ marginBottom: 14 }}>
        <Card title="Mentions per day" question="When was this name in the news?" query={entity}
          empty={!e?.mentions}
          table={() => (
            <table><caption>Articles mentioning this entity per day</caption>
              <thead><tr><th scope="col">Day</th><th className="num" scope="col">Articles</th>
                <th className="num" scope="col">Mean tone</th></tr></thead>
              <tbody>{e?.series.map((d) => (
                <tr key={d.day}><td>{formatDay(d.day, true)}</td><td className="num">{d.mentions}</td>
                  <td className="num">{formatScore(d.avg_sentiment)}</td></tr>))}</tbody>
            </table>
          )}>
          {() => <DailyLine data={e!.series} dataKey="mentions" label="Articles" />}
        </Card>
        <Card title="Mentioned alongside" question="Who else appears in the same articles?" query={entity}
          empty={!e?.co_mentions.length}>
          {() => (
            <RankList unit="shared articles" items={e!.co_mentions.map((c) => ({
              key: c.id, label: c.name, href: withFilters(`/entities/${c.id}`, filters), value: c.together,
              sublabel: ENTITY_TYPE_LABEL[c.type],
            }))} />
          )}
        </Card>
      </div>
      <div className="grid grid--2">
        <div className="stack">
          <Card title="In which topics" query={entity} empty={!e?.topics.length}>
            {() => (
              <RankList unit="articles" items={e!.topics.map((t) => ({
                key: t.slug, label: t.name_en, href: withFilters(`/topics/${t.slug}`, filters), value: t.articles,
              }))} />
            )}
          </Card>
          <Card title="By outlet" question="Who covers this name, and in what tone?" query={entity}
            empty={!e?.sources.length}>
            {() => (
              <table>
                <thead><tr><th scope="col">Outlet</th><th className="num" scope="col">Articles</th>
                  <th className="num" scope="col">Mean tone</th></tr></thead>
                <tbody>{e!.sources.map((s) => (
                  <tr key={s.slug}><td>{s.name}</td><td className="num">{s.articles}</td>
                    <td className="num">{formatScore(s.avg_sentiment)}</td></tr>))}</tbody>
              </table>
            )}
          </Card>
        </div>
        <Card title="Articles" query={articles} empty={!articles.data?.items.length}
          actions={<Link className="btn btn--ghost btn--sm" to={withFilters("/articles", filters, { entity: String(id) })}>All</Link>}>
          {() => <ArticleList items={articles.data!.items} />}
        </Card>
      </div>
    </>
  );
}
