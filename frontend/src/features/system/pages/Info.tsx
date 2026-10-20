import { Link } from "react-router-dom";

import { useTitle } from "@/shared/hooks/useTitle";
import { getLang, labels, t } from "@/shared/i18n";
import { formatDateTime, formatInt, formatRelative } from "@/shared/lib/format";
import { Card } from "@/ui/Card";
import { NotFoundState } from "@/ui/States";
import { useStatus, useTaxonomy } from "../api";
import { type AboutProps, CONTACT_IS_EMAIL, CONTACT_URL } from "./about";
import { AboutSq } from "./AboutSq";


export function AboutPage() {
  useTitle(t("Methodology"), t("How GJURMË collects, analyses and presents news data, and its limitations."));
  const taxonomy = useTaxonomy();
  const status = useStatus();
  const props = { topics: taxonomy.data?.length ?? 19, status: status.data };
  return getLang() === "sq" ? <AboutSq {...props} /> : <AboutEn {...props} />;
}

function AboutEn({ topics, status }: AboutProps) {
  return (
    <div className="prose">
      <h1>Methodology, sources &amp; limitations</h1>
      <p>
        <strong>GJURMË</strong> (Albanian: “trace, footprint”) follows what Albanian-language and
        regional media publish, groups the articles that report the same event into stories, and
        shows who covered each story and who did not — by the outlets’ perspective, region and
        ownership. It also turns the news into comparable numbers: which topics dominate, who is in
        the news, how the tone of coverage shifts, and how outlets differ.
      </p>

      <h2>1. Collection</h2>
      <ul>
        <li>Only public <strong>RSS feeds</strong> are read, every 15 minutes, identifying ourselves with a
          clear user agent. <code>robots.txt</code> is respected; outlets that block automated access are
          not included.</li>
        <li>We store the <strong>headline, link, publication time, feed categories</strong> and a short
          feed excerpt used only as input to the analysis. Excerpts are never shown and are deleted after
          90 days. Article pages are never scraped; images are never copied.</li>
        <li>Duplicates are removed (same link, same headline republished). Near-identical headlines from
          different outlets are kept — each outlet’s coverage counts — and linked as the same story.</li>
      </ul>

      <h2 id="analysis">2. AI analysis</h2>
      {status && status.analysis.mode !== "ai" && status.analysis.mode !== "none" && (
        <p className="banner" role="note">
          <strong>Current mode:</strong>{" "}
          {status.analysis.mode === "rules" ? "all" : `${Math.round((status.analysis.rule_based_share ?? 0) * 100)}% of`}{" "}
          recent articles were analysed by <em>keyword rules</em> instead of the language model described
          below: topics and tone come from lists of Albanian keywords, names from capitalised words,
          and there is no summary. This is much less accurate. Every article page says which method was used.
        </p>
      )}
      <ul>
        <li>Each headline + excerpt is analysed by a large language model (each article page names the model) that returns
          a structured record: primary topic (from a fixed list of {topics} topics),
          up to three secondary topics, tone, event type, people/organisations/places, countries, a
          one-sentence English summary and a confidence score.</li>
        <li>The output is validated against a strict schema. Names that do not appear in the headline or
          excerpt are discarded as likely hallucinations. Failed analyses are retried and logged, never
          silently dropped.</li>
        <li><strong>Tone</strong> means how negative or positive the reported situation is for the
          general public (crime and accidents score negative; agreements and achievements positive). It
          is not a judgement of the outlet’s bias.</li>
      </ul>

      <h2>3. How the numbers work</h2>
      <ul>
        <li>Days are local calendar days in Kosovo/Albania (Europe/Tirane).</li>
        <li><strong>Topic momentum</strong>: articles in the last 7 days vs the 7 days before;
          growth = (now − before) / max(before, 5).</li>
        <li><strong>Spikes</strong>: mentions in the last 24 hours compared with the mean and standard
          deviation of daily mentions over the previous 28 days (z-score ≥ 3 and ≥ 5 mentions).</li>
        <li><strong>Moving averages</strong> are trailing 7-day means.</li>
      </ul>

      <h2 id="stories">4. Stories, coverage bars and blindspots</h2>
      <ul>
        <li>A <strong>story</strong> groups the articles of different outlets that report the same
          event, so you can see who covered it and compare their headlines. Headline, excerpt and
          the names the analysis found are compared as weighted word lists (rare words such as names
          and places weigh more; Albanian word endings are folded, so “Kurtin” and “Kurtit” match).
          An article joins the most similar story if the whole story stays within 48 hours, if its
          headline shares more than a person’s name with the story, and unless the headlines name
          different places, people or numbers — “a fire in Prizren” and “a fire in Gjakovë”, or
          “12 dead” and “3 dead”, stay separate.</li>
        <li>The grouping errs on the side of keeping stories apart: two different events merged into
          one would misstate coverage. Some paraphrases of one event therefore end up as separate
          stories.</li>
        <li><strong>Coverage bars</strong> count each outlet once per story and split them by the
          outlet’s perspective, region (where it is based), ownership or factuality. The headline
          shown for a story is the one whose wording is closest to all the others.</li>
        <li><strong>Blindspot</strong>: at least 3 rated outlets covered a story, 60% or more of them
          from one side and at most 15% from the other — or the story is about a country (named in
          at least half of its analysed articles) whose own outlets did not report it.</li>
        <li><strong>Reported first</strong> is the outlet with the earliest publication time among a
          story’s articles, as stated by the feeds.</li>
        <li>The <strong>trace</strong> on a story page draws every report as one mark on a single time
          line, coloured by the chosen split; the first report is the taller mark.</li>
      </ul>

      <h2 id="ratings">5. How outlets are rated</h2>
      <ul>
        <li><strong>Perspective</strong> (left · lean left · center · lean right · right) and
          <strong> factuality</strong> (very high … very low) are editorial judgements about the
          <em> outlet</em>, never about a single article. GJURMË only shows a rating that rests on a
          documented review, and states its basis on the outlet’s page. Until then the outlet is
          shown as <em>unrated</em> (a hatched segment in every bar).</li>
        <li><strong>Ownership</strong> (private company, media group, public broadcaster,
          international public media, non-profit …) comes from public information about the
          publisher.</li>
        <li>The colours follow Ground News — blue for left, gray for center, red for right — so its
          readers can read the bars at once. They are a convention for the scale, not party colours.
          Elsewhere on the site, colour appears only in charts and bars; text and links are black.</li>
        <li>Ratings can be wrong or out of date. Outlets and readers can ask for a correction through
          the contact below.</li>
      </ul>

      <h2 id="my-news">6. My news bias</h2>
      <p>
        When you open an article from GJURMË, this browser notes the outlet, so the{" "}
        <Link to="/my-news">My news bias</Link> page can show the balance of what you read. The
        record never leaves your browser (it is kept in its local storage, for at most 90 days) and
        can be cleared on that page at any time.
      </p>

      <h2>7. Limitations</h2>
      <ul>
        <li>The AI can misclassify topics or tone, merge or split names (“Kurti” vs “Albin Kurti”), and
          miss entities. Treat individual labels as indicative; aggregates are more reliable.</li>
        <li>Coverage is limited to the outlets below and to what their feeds expose; high-volume outlets
          weigh more in totals.</li>
        <li>Feeds sometimes lack or mislabel publication times; those articles are marked “(est.)”.</li>
      </ul>

      <h2>8. Sources</h2>
      {status ? (
        <ul>
          {status.sources.map((s) => (
            <li key={s.slug}>{s.name} — {s.is_active ? "active" : "not collected"}
              {s.last_success_at && <>, last read {formatRelative(s.last_success_at)}</>}</li>
          ))}
        </ul>
      ) : <p>Loading…</p>}

      <h2 id="contact">9. Corrections, removal requests &amp; privacy</h2>
      <p>
        Publishers or individuals can request correction or removal of any item; we hide it from all
        pages and statistics.{" "}
        {CONTACT_IS_EMAIL ? (
          <>Write to <a href={CONTACT_URL}>{CONTACT_URL.slice("mailto:".length)}</a> with the article link.</>
        ) : (
          <>
            Please open an issue at{" "}
            <a href={CONTACT_URL} rel="noopener noreferrer">the project repository</a> with the
            article link (issues are public).
          </>
        )}{" "}
        GJURMË uses no cookies, no trackers and no analytics; its own logs keep no full IP addresses
        (they are truncated or hashed before being written), though the hosting provider may keep
        its access logs for a short time. The reading record behind “My news bias” stays in your
        browser.
      </p>
      <p>
        Developers: the full data is available through the documented <a href="/api/docs">public API</a>.
      </p>
    </div>
  );
}

const STATUS_LABEL: Readonly<Record<string, string>> = labels({ ok: "ok", degraded: "degraded", stale: "stale" });
const RUN_LABEL: Readonly<Record<string, string>> = labels({
  succeeded: "succeeded",
  partial: "partial",
  failed: "failed",
  running: "running",
  skipped_locked: "skipped (another run was busy)",
  abandoned: "abandoned",
});
const FEED_LABEL: Readonly<Record<string, string>> = labels({
  verified: "verified",
  failing: "failing",
  unverified: "unverified",
});

export function StatusPage() {
  useTitle(t("Status"), t("Pipeline freshness and source health."));
  const status = useStatus();
  const s = status.data;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("System status")}</h1>
          <p>{t("Live health of the collection pipeline. It runs automatically every 15 minutes.")}</p>
        </div>
      </div>
      <div className="stack">
        <Card title={t("Pipeline")} query={status}>
          {() => (
            <dl className="facts">
              <dt>{t("Status")}</dt><dd><strong>{STATUS_LABEL[s!.status] ?? s!.status}</strong></dd>
              <dt>{t("Last successful run")}</dt><dd>{formatDateTime(s!.last_success_at)} ({formatRelative(s!.last_success_at)})</dd>
              <dt>{t("Last run result")}</dt><dd>{s!.last_run_status ? (RUN_LABEL[s!.last_run_status] ?? s!.last_run_status) : "—"}</dd>
              <dt>{t("Scheduler heartbeat")}</dt><dd>{formatRelative(s!.scheduler_heartbeat_at)}</dd>
              <dt>{t("Articles, last 24 h")}</dt><dd>{formatInt(s!.articles_last_24h)}</dd>
              <dt>{t("Waiting for analysis")}</dt><dd>{formatInt(s!.enrichment_backlog)}</dd>
              <dt>{t("Version")}</dt><dd>{s!.version}</dd>
            </dl>
          )}
        </Card>
        <Card title={t("Sources")} query={status} empty={!s?.sources.length}>
          {() => (
            <table>
              <thead><tr><th scope="col">{t("Source")}</th><th scope="col">{t("State")}</th><th scope="col">{t("Feed")}</th>
                <th scope="col">{t("Last successful read")}</th><th className="num" scope="col">{t("Failures in a row")}</th></tr></thead>
              <tbody>{s!.sources.map((src) => (
                <tr key={src.slug}><td>{src.name}</td><td>{src.is_active ? t("active") : t("not collected")}</td>
                  <td>{FEED_LABEL[src.verification_status] ?? src.verification_status}</td><td>{formatDateTime(src.last_success_at)}</td>
                  <td className="num">{src.consecutive_failures}</td></tr>))}</tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  );
}

export function NotFoundPage() {
  useTitle(t("Not found"), undefined, { index: false });
  return <NotFoundState title={t("Page not found")} />;
}
