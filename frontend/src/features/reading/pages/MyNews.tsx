import { Link } from "react-router-dom";

import { useSources } from "@/features/sources";
import { StoryCard, StoryCoverage, useBlindspots } from "@/features/stories";
import { useTitle } from "@/shared/hooks/useTitle";
import { formatInt, formatPercent } from "@/shared/lib/format";
import { BIAS_GROUP_LABEL, type Lens, LENS_LABEL } from "@/shared/model/ratings";
import { clearReading, useReading } from "@/stores/reading";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { missingSide, readingCoverage } from "../readingCoverage";

/**
 * Ground News' "My News Bias", without accounts: the reading log lives in this browser only
 * (localStorage) and is never sent anywhere. It counts the outlets of articles opened from
 * GJURMË, and shows their balance by perspective, region, ownership and factuality.
 */
export default function MyNewsPage() {
  useTitle("My news bias", "The balance of the outlets you read, kept only in your browser.");
  const reading = useReading();
  const sources = useSources({ days: 90 });
  const blind = useBlindspots({ days: 7 });
  const bySlug = new Map((sources.data ?? []).map((s) => [s.slug, s]));
  const cov = readingCoverage(reading, bySlug);
  const missing = missingSide(cov);
  const outlets = new Map<string, number>();
  reading.forEach((e) => outlets.set(e.s, (outlets.get(e.s) ?? 0) + 1));
  const suggestions = (blind.data?.items ?? []).filter((s) =>
    s.blindspots.some((b) => b.kind === "perspective" && (!missing || b.missing !== missing)),
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>My news bias</h1>
          <p>
            The outlets behind the articles you opened from GJURMË, and how they balance out. This
            record stays in this browser only: no account, no cookies, nothing sent to a server.
          </p>
        </div>
        {reading.length > 0 && (
          <button type="button" className="btn" onClick={() => clearReading()}>Clear my history</button>
        )}
      </div>
      {!reading.length ? (
        <section className="card">
          <h2>Nothing read yet</h2>
          <p className="card__question" style={{ marginTop: 6 }}>
            Open a few articles from the <Link to="/">stories</Link> — this page then shows whether you
            mostly read one side, one country or one kind of owner.
          </p>
        </section>
      ) : (
        <div className="stack">
          <div className="grid grid--kpi">
            <div className="card stat">
              <span className="stat__label">Articles opened</span>
              <span className="stat__value">{formatInt(reading.length)}</span>
              <span className="stat__sub">last 90 days</span>
            </div>
            <div className="card stat">
              <span className="stat__label">Different outlets</span>
              <span className="stat__value">{formatInt(outlets.size)}</span>
            </div>
            <div className="card stat">
              <span className="stat__label">Your blind side</span>
              <span className="stat__value stat__value--text">{missing ? BIAS_GROUP_LABEL[missing] : "None detected"}</span>
              <span className="stat__sub">{missing ? `few ${missing}-leaning outlets in your reading` : "needs 5+ articles from rated outlets"}</span>
            </div>
          </div>
          <div className="grid grid--2">
            <Card title="Your balance" question="Outlets of the articles you opened, counted once per article.">
              {() => (
                <div className="stack" style={{ gap: 16 }}>
                  {(["perspective", "region", "ownership", "factuality"] as Lens[]).map((l) => (
                    <div key={l} className="stack" style={{ gap: 6 }}>
                      <h3>{LENS_LABEL[l]}</h3>
                      <StoryCoverage coverage={cov} lens={l} unit={["article", "articles"]} />
                    </div>
                  ))}
                </div>
              )}
            </Card>
            <Card title="Outlets you read" query={sources}>
              {() => (
                <RankList unit="articles" items={[...outlets.entries()].sort((a, b) => b[1] - a[1]).map(([slug, n]) => ({
                  key: slug, label: bySlug.get(slug)?.name ?? slug, href: `/sources/${slug}`, value: n,
                  meta: <> · {formatPercent(n / reading.length)}</>,
                }))} />
              )}
            </Card>
          </div>
          <Card title="Step outside your bubble" query={blind} empty={!suggestions.length}
            question={missing ? `Stories that ${missing}-leaning outlets covered and the rest barely did.` : "This week's blindspots."}
            emptyText="No blindspot stories this week.">
            {() => <div>{suggestions.slice(0, 6).map((s) => <StoryCard key={s.id} story={s} lens="perspective" compact />)}</div>}
          </Card>
        </div>
      )}
    </>
  );
}
