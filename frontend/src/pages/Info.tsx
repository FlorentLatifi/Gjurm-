import { Link } from "react-router-dom";

import { useStatus, useTaxonomy } from "../api/hooks";
import { Card } from "../components/Card";
import { formatDateTime, formatInt, formatRelative } from "../lib/format";
import { useTitle } from "../lib/useTitle";

// Where correction and removal requests go. Set VITE_CONTACT_URL at build time (e.g. a mailto:
// address) so people do not have to post removal requests publicly; GitHub issues are public.
const CONTACT_URL = /^(mailto:|https:\/\/)/.test(import.meta.env.VITE_CONTACT_URL ?? "")
  ? (import.meta.env.VITE_CONTACT_URL as string)
  : "https://github.com/FlorentLatifi/Gjurm-/issues";
const CONTACT_IS_EMAIL = CONTACT_URL.startsWith("mailto:");

export function AboutPage() {
  useTitle("Methodology", "How GJURMË collects, analyses and presents news data, and its limitations.");
  const taxonomy = useTaxonomy();
  const status = useStatus();
  return (
    <div className="prose">
      <h1 style={{ color: "var(--ink)" }}>Methodology, sources &amp; limitations</h1>
      <p>
        <strong>GJURMË</strong> (Albanian: “trace, footprint”) follows what Albanian-language and
        regional media publish and turns it into comparable numbers: which topics dominate, who is in
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
      {status.data && status.data.analysis.mode !== "ai" && status.data.analysis.mode !== "none" && (
        <p className="banner" role="note">
          <strong>Current mode:</strong>{" "}
          {status.data.analysis.mode === "rules" ? "all" : `${Math.round((status.data.analysis.rule_based_share ?? 0) * 100)}% of`}{" "}
          recent articles were analysed by <em>keyword rules</em> instead of the language model described
          below: topics and tone come from lists of Albanian keywords, names from capitalised words,
          and there is no summary. This is much less accurate. Every article page says which method was used.
        </p>
      )}
      <ul>
        <li>Each headline + excerpt is analysed by a large language model (each article page names the model) that returns
          a structured record: primary topic (from a fixed list of {taxonomy.data?.length ?? 19} topics),
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

      <h2>4. Limitations</h2>
      <ul>
        <li>The AI can misclassify topics or tone, merge or split names (“Kurti” vs “Albin Kurti”), and
          miss entities. Treat individual labels as indicative; aggregates are more reliable.</li>
        <li>Coverage is limited to the outlets below and to what their feeds expose; high-volume outlets
          weigh more in totals.</li>
        <li>Feeds sometimes lack or mislabel publication times; those articles are marked “(est.)”.</li>
      </ul>

      <h2>5. Sources</h2>
      {status.data ? (
        <ul>
          {status.data.sources.map((s) => (
            <li key={s.slug}>{s.name} — {s.is_active ? "active" : "not collected"}
              {s.last_success_at && <>, last read {formatRelative(s.last_success_at)}</>}</li>
          ))}
        </ul>
      ) : <p>Loading…</p>}

      <h2 id="contact">6. Corrections, removal requests &amp; privacy</h2>
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
        GJURMË uses no cookies, no trackers and no analytics; server logs keep no full IP addresses
        (they are truncated before being written).
      </p>
      <p>
        Developers: the full data is available through the documented <a href="/api/docs">public API</a>.
      </p>
    </div>
  );
}

export function StatusPage() {
  useTitle("Status", "Pipeline freshness and source health.");
  const status = useStatus();
  const s = status.data;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>System status</h1>
          <p>Live health of the collection pipeline. It runs automatically every 15 minutes.</p>
        </div>
      </div>
      <div className="stack">
        <Card title="Pipeline" query={status}>
          {() => (
            <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "6px 18px", margin: 0 }}>
              <dt>Status</dt><dd style={{ margin: 0 }}><strong>{s!.status}</strong></dd>
              <dt>Last successful run</dt><dd style={{ margin: 0 }}>{formatDateTime(s!.last_success_at)} ({formatRelative(s!.last_success_at)})</dd>
              <dt>Last run result</dt><dd style={{ margin: 0 }}>{s!.last_run_status ?? "—"}</dd>
              <dt>Scheduler heartbeat</dt><dd style={{ margin: 0 }}>{formatRelative(s!.scheduler_heartbeat_at)}</dd>
              <dt>Articles, last 24 h</dt><dd style={{ margin: 0 }}>{formatInt(s!.articles_last_24h)}</dd>
              <dt>Waiting for analysis</dt><dd style={{ margin: 0 }}>{formatInt(s!.enrichment_backlog)}</dd>
              <dt>Version</dt><dd style={{ margin: 0 }}>{s!.version}</dd>
            </dl>
          )}
        </Card>
        <Card title="Sources" query={status} empty={!s?.sources.length}>
          {() => (
            <table>
              <thead><tr><th scope="col">Source</th><th scope="col">State</th><th scope="col">Feed</th>
                <th scope="col">Last successful read</th><th className="num" scope="col">Failures in a row</th></tr></thead>
              <tbody>{s!.sources.map((src) => (
                <tr key={src.slug}><td>{src.name}</td><td>{src.is_active ? "active" : "not collected"}</td>
                  <td>{src.verification_status}</td><td>{formatDateTime(src.last_success_at)}</td>
                  <td className="num">{src.consecutive_failures}</td></tr>))}</tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  );
}

export function NotFoundPage() {
  useTitle("Not found");
  return (
    <div className="state" style={{ padding: "64px 0" }}>
      <h1>Page not found</h1>
      <p>The page you are looking for does not exist.</p>
      <Link className="btn" to="/">Go to the overview</Link>
    </div>
  );
}
