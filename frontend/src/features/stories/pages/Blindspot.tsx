import { useSearchParams } from "react-router-dom";

import { FilterBar } from "@/features/filters";
import type { Blindspot } from "@/shared/api/types";
import { useTitle } from "@/shared/hooks/useTitle";
import { useApiQuery } from "@/shared/query/apiQuery";
import { formatInt } from "@/shared/lib/format";
import { Card } from "@/ui/Card";
import { StoryCard } from "../StoryCard";
import { blindspotKind, blindspotQueries } from "../queries";

const PRESETS = [
  { days: 3, label: "3 days" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
] as const;

const KINDS: { kind: Blindspot["kind"] | ""; label: string }[] = [
  { kind: "", label: "All" },
  { kind: "perspective", label: "Perspective" },
  { kind: "region", label: "Region" },
];

/** Ground News' Blindspot feed: stories that one side of the spectrum, or one country, missed. */
export default function BlindspotPage() {
  useTitle("Blindspot", "Stories one side of the spectrum, or one country's media, barely covered.");
  const [params, setParams] = useSearchParams();
  const kind = blindspotKind(params);
  const query = useApiQuery(blindspotQueries(params).blindspots);
  const items = query.data?.items ?? [];
  const forLeft = items.filter((s) => s.blindspots.some((b) => b.kind === "perspective" && b.missing === "left"));
  const forRight = items.filter((s) => s.blindspots.some((b) => b.kind === "perspective" && b.missing === "right"));
  const byRegion = items.filter((s) => s.blindspots.some((b) => b.kind === "region"));

  const setKind = (k: string) =>
    setParams((prev) => {
      const out = new URLSearchParams(prev);
      if (k) out.set("kind", k);
      else out.delete("kind");
      return out;
    });

  const column = (title: string, question: string, list: typeof items, lens: "perspective" | "region") => (
    <Card title={`${title} · ${formatInt(list.length)}`} question={question} query={query} empty={!list.length}
      emptyText="None in this period.">
      {() => <div>{list.map((s) => <StoryCard key={s.id} story={s} lens={lens} compact />)}</div>}
    </Card>
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Blindspot</h1>
          <p>
            Stories that outlets on one side barely covered — or that are about a country whose own
            outlets did not report them. Reading them is the quickest way out of a news bubble.
          </p>
        </div>
      </div>
      <FilterBar presets={PRESETS} defaultDays={7} showSources={false}>
        <div className="segmented" role="group" aria-label="Blindspot type">
          {KINDS.map((k) => (
            <button key={k.label} type="button" aria-pressed={kind === k.kind} onClick={() => setKind(k.kind)}>
              {k.label}
            </button>
          ))}
        </div>
      </FilterBar>
      <div className="grid grid--3">
        {kind !== "region" && column("For the left", "Mostly right-leaning outlets covered these; few or no left-leaning ones.", forLeft, "perspective")}
        {kind !== "region" && column("For the right", "Mostly left-leaning outlets covered these; few or no right-leaning ones.", forRight, "perspective")}
        {kind !== "perspective" && column("By region", "About a country whose outlets did not cover them.", byRegion, "region")}
      </div>
      {query.data && <p className="card__foot" style={{ marginTop: 12 }}>{query.data.method}</p>}
    </>
  );
}
