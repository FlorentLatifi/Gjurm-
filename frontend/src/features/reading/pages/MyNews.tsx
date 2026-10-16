import { Link } from "react-router-dom";

import { StoryCard, StoryCoverage } from "@/features/stories";
import { useTitle } from "@/shared/hooks/useTitle";
import { formatInt, formatPercent } from "@/shared/lib/format";
import { availableLenses, BIAS_GROUP_LABEL, type Lens, LENS_LABEL } from "@/shared/model/ratings";
import { clearReading, useReading } from "@/stores/reading";
import { Card } from "@/ui/Card";
import { RankList } from "@/ui/RankList";
import { missingSide, readingCoverage } from "../readingCoverage";
import { useApiQuery } from "@/shared/query/apiQuery";
import { myNewsQueries } from "../queries";
import { t, tn } from "@/shared/i18n";

/**
 * Ground News' "My News Bias", without accounts: the reading log lives in this browser only
 * (localStorage) and is never sent anywhere. It counts the outlets of articles opened from
 * GJURMË, and shows their balance by perspective, region, ownership and factuality.
 */
export default function MyNewsPage() {
  useTitle(t("My news bias"), t("The balance of the outlets you read, kept only in your browser."));
  const reading = useReading();
  const queries = myNewsQueries();
  const sources = useApiQuery(queries.sources);
  const blind = useApiQuery(queries.blindspots);
  const bySlug = new Map((sources.data ?? []).map((s) => [s.slug, s]));
  const cov = readingCoverage(reading, bySlug);
  const missing = missingSide(cov);
  const outlets = new Map<string, number>();
  reading.forEach((e) => outlets.set(e.s, (outlets.get(e.s) ?? 0) + 1));
  // Until outlets have perspective ratings, the balance and the suggestions go by region.
  const rated = (sources.data ?? []).some((s) => s.bias !== "unrated");
  const kind = rated ? "perspective" : "region";
  const lenses = (["perspective", "region", "ownership", "factuality"] as Lens[]).filter((l) =>
    availableLenses([cov]).includes(l),
  );
  const suggestions = (blind.data?.items ?? []).filter((s) =>
    s.blindspots.some((b) => b.kind === kind && (!missing || b.missing !== missing)),
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("My news bias")}</h1>
          <p>
            {t("The outlets behind the articles you opened from GJURMË, and how they balance out. This record stays in this browser only: no account, no cookies, nothing sent to a server.")}
          </p>
        </div>
        {reading.length > 0 && (
          <button type="button" className="btn" onClick={() => clearReading()}>{t("Clear my history")}</button>
        )}
      </div>
      {!reading.length ? (
        <section className="card">
          <h2>{t("Nothing read yet")}</h2>
          <p className="card__question mt-2">
            {t("Open a few articles from the stories — this page then shows whether you mostly read one side, one country or one kind of owner.")}{" "}
            <Link to="/">{t("Go to the top stories")}</Link>
          </p>
        </section>
      ) : (
        <div className="stack">
          <div className="grid grid--kpi">
            <div className="card stat">
              <span className="stat__label">{t("Articles opened")}</span>
              <span className="stat__value">{formatInt(reading.length)}</span>
              <span className="stat__sub">{t("last 90 days")}</span>
            </div>
            <div className="card stat">
              <span className="stat__label">{t("Different outlets")}</span>
              <span className="stat__value">{formatInt(outlets.size)}</span>
            </div>
            <div className="card stat">
              <span className="stat__label">{t("Your blind side")}</span>
              <span className="stat__value stat__value--text">
                {missing ? BIAS_GROUP_LABEL[missing] : rated ? t("None detected") : t("Not yet known")}
              </span>
              <span className="stat__sub">
                {missing === "left"
                  ? t("few left-leaning outlets in your reading")
                  : missing === "right"
                    ? t("few right-leaning outlets in your reading")
                    : rated
                      ? t("needs 5+ articles from rated outlets")
                      : t("outlets have no perspective ratings yet")}
              </span>
            </div>
          </div>
          <div className="grid grid--2">
            <Card title={t("Your balance")} question={t("Outlets of the articles you opened, counted once per article.")}>
              {() => (
                <div className="stack">
                  {lenses.map((l) => (
                    <div key={l} className="stack stack--tight">
                      <h3>{LENS_LABEL[l]}</h3>
                      <StoryCoverage coverage={cov} lens={l} unit={(n) => tn(n, "{n} article", "{n} articles")} />
                    </div>
                  ))}
                </div>
              )}
            </Card>
            <Card title={t("Outlets you read")} query={sources}>
              {() => (
                <RankList unit={(n) => tn(n, "{n} article", "{n} articles")} items={[...outlets.entries()].sort((a, b) => b[1] - a[1]).map(([slug, n]) => ({
                  key: slug, label: bySlug.get(slug)?.name ?? slug, href: `/sources/${slug}`, value: n,
                  meta: <> · {formatPercent(n / reading.length)}</>,
                }))} />
              )}
            </Card>
          </div>
          <Card title={t("Step outside your bubble")} query={blind} empty={!suggestions.length}
            question={
              missing === "left"
                ? t("Stories that left-leaning outlets covered and the rest barely did.")
                : missing === "right"
                  ? t("Stories that right-leaning outlets covered and the rest barely did.")
                  : rated
                    ? t("This week's blindspots.")
                    : t("This week's stories about a country whose own outlets did not report them.")
            }
            emptyText={t("No blindspot stories this week.")}>
            {() => <div>{suggestions.slice(0, 6).map((s) => <StoryCard key={s.id} story={s} lens={kind} compact />)}</div>}
          </Card>
        </div>
      )}
    </>
  );
}
