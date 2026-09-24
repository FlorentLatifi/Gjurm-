# Portfolio notes

Material for CVs, GitHub, LinkedIn and interviews. Every number here is verified in this repository (tests, CI runs, benchmark). Keep it that way: after launch, replace the "not yet deployed" wording with real figures from `/api/v1/admin/costs` and `/api/v1/status`, not estimates.

## GitHub

**About (description):**
AI news intelligence for Albanian-language media: RSS ingestion, 4-layer dedup, Claude enrichment with validation and a hard budget, PostgreSQL analytics, FastAPI and an accessible React dashboard. Tested, self-monitoring, documented.

**Topics:** `news-analytics` `nlp` `llm` `claude` `data-engineering` `etl` `fastapi` `postgresql` `react` `typescript` `docker` `github-actions` `albanian` `kosovo`

## CV bullets

- Designed and built **GJURMË**, an end-to-end news-intelligence platform for Albanian-language media: RSS ingestion, cleaning and 4-layer deduplication, LLM enrichment, PostgreSQL analytics, a typed FastAPI and a React/TypeScript dashboard, packaged for production with Docker, Caddy and GitHub Actions CI/CD.
- Built a **reliable LLM pipeline** on Claude with structured outputs, schema validation and repair, and an entity-grounding check that drops names not present in the source text. It runs under a hard daily budget (thread-safe reservations), a circuit breaker and a kill switch, with per-call token and cost lineage. Estimated cost ≈ $0.004 per article.
- Made the pipeline **idempotent and self-operating**: advisory-lock overlap protection, crash recovery, 12 data-quality checks per run, webhook alerting, an external uptime/freshness monitor, nightly backups with automated restore verification, and deploys with health-checked automatic rollback.
- **Measured performance at one year of data** (365k articles, 1.09M entity mentions). Profiling with `EXPLAIN ANALYZE` led to a covering-index migration, query rewrites and a fix for PostgreSQL generic-plan regressions: entity analytics became 1.5–4.5× faster with identical results.
- Wrote **218 backend tests** (92 against real PostgreSQL, including failure injection for timeouts, malformed feeds, LLM errors, budget exhaustion and crashes) and **40 Playwright end-to-end tests** with axe-core accessibility checks. CI runs lint, strict typing, secret scanning, dependency audits and Trivy image scanning.
- Found and fixed issues **before production** through testing and scanning: an HTTP-304 bug that would have auto-disabled healthy sources, 17 HIGH CVEs in an upstream web-server binary (rebuilt from source), and IP addresses in logs that contradicted the published privacy statement.

Short version (one line):
> Built an AI news-intelligence platform (Python/FastAPI, PostgreSQL, Claude, React) with validated LLM enrichment under a hard budget, 4-layer dedup, measured query optimization (1.5–4.5×), and 250+ automated tests.

## LinkedIn post

> I built **GJURMË** ("trace" in Albanian), an open-source news-intelligence platform for Albanian-language media.
>
> It is built to read Kosovo news feeds every 15 minutes, remove duplicates, and ask Claude to classify each headline: topic, tone, people, organizations, places, plus a one-line English summary. A public dashboard then answers questions like *what dominates coverage this week?*, *who is suddenly in the news?* and *how do outlets differ?*
>
> The engineering is the part I enjoyed most:
> • The model can't invent names: every extracted entity has to be found in the source text, with Albanian inflection handled.
> • LLM spend has a hard daily cap and a kill switch; every call is logged with tokens and cost.
> • One year of simulated data (365k articles) exposed a PostgreSQL generic-plan trap and a missing index; fixing them made entity queries up to 4.5× faster.
> • 250+ automated tests, including failure injection, and an accessibility check on every page.
> • Metadata only: no article text is republished, and every item links to its source.
>
> Stack: Python, FastAPI, PostgreSQL, Claude, React/TypeScript, Docker, GitHub Actions.
> Code and docs: https://github.com/FlorentLatifi/Gjurm-

(After launch, add the live URL and one real insight from the data.)

## 30-second pitch

"GJURMË is a news-intelligence platform for Albanian-language media. It reads the major Kosovo outlets every 15 minutes, removes duplicates, and uses Claude to tag each story with topic, tone and the people and places involved. It checks that the AI didn't invent anything and keeps spending under a hard daily cap. A dashboard then shows what dominates coverage, who is suddenly in the news, and how outlets differ. I built the whole thing: the data pipeline, the AI layer, the API, the frontend, the tests, and the deployment and monitoring."

## 2-minute explanation

"The problem: Albanian-language news is spread across dozens of high-volume portals, and there's no tool that answers basic media questions for that language space, like which topics are rising, who is in the news, or whether outlet A is more negative than outlet B.

The pipeline has four stages, all in one Python codebase over PostgreSQL. **Ingest** fetches RSS feeds politely: it respects robots.txt, uses conditional requests, and isolates each source so one broken feed can't stop the rest. **Process** normalizes text (Albanian characters, broken encodings, dates in local time) and deduplicates in four layers, from identical feed entries up to near-verbatim copies across outlets. I calibrated that last layer on real headlines, because the obvious threshold merged different events that happened in the same city. **Enrich** sends each headline and excerpt to Claude with a strict JSON schema. The output is validated and repaired, and every entity must appear in the source text, which catches the model 'helpfully' adding first names. Cost is controlled with a daily budget that reserves money before each call, plus caching and a kill switch. **Quality checks and alerts** run after every cycle.

On top of that sit a typed FastAPI and a React dashboard with transparent methods: momentum is period-over-period growth with damping, and spikes are z-scores against a 28-day baseline. The dashboard is keyboard- and screen-reader-friendly, with a colour-blind-safe palette.

For operations, it runs on a single server with Docker. CI runs 250+ tests plus security scanning. Deploys check health and roll back automatically, and backups are restore-tested weekly. Before calling it done, I benchmarked a year of data. That found a PostgreSQL planning issue and a missing index, and fixing them made the entity queries up to 4.5 times faster. The scanner also caught vulnerabilities in the web server binary, which I fixed by building it from source."

## Architecture in one whiteboard

```
RSS feeds ─► ingest ─► raw.* ─► process/dedup ─► core.articles ─► enrich (Claude) ─► core.*
                                                                         │
                         quality checks + alerts ◄───────────────────────┘
core.* ─► analytics SQL ─► FastAPI (cache, rate limit) ─► Caddy (HTTPS, CSP) ─► React SPA
GitHub Actions: CI/CD · weekly source validation · external uptime monitor
```

## Interview questions and answers

**Why a monolith and not microservices?**
One data source type, one database, ~1,000 articles a day, and one operator. Services would add network contracts, deployment surface and failure modes with nothing gained. The stages still talk only through database tables, so any of them can be split out later. The API and the scheduler already run as separate processes from one image, so they fail independently.

**How do you stop the LLM from hallucinating entities?**
Three layers. The prompt says precision beats coverage and names must appear in the text. Structured outputs force valid JSON with fixed vocabularies. Then a grounding check drops any entity whose name tokens aren't in the headline or excerpt: all tokens for people, at least half for organizations. It uses prefix matching, because Albanian inflects names ("Prishtinës" → "Prishtina"). Dropped entities are counted, and a data-quality check alerts if the rate rises.

**How do you control LLM cost?**
A daily budget that *reserves* a pessimistic estimate before each call and settles to the real cost afterwards, so concurrent workers can't overshoot. It's tested with threads. Dedup and an enrichment cache mean nothing is paid for twice. The system prompt is prompt-cached. There's also a per-run cap and a kill switch in the database that needs no redeploy. Spend is computed from the database, so a restart can't reset it.

**What happens if the process crashes mid-run?**
Nothing is lost. Each stage picks up its work from table state (`processed_at IS NULL`, `enrichment_status = 'pending'`), and every write is an idempotent upsert. The run holds a PostgreSQL advisory lock that dies with the connection; the next run sees a `running` row without a lock and marks it `abandoned`. There are tests for exactly this.

**How do you deploy without downtime risk and roll back safely?**
CI builds images tagged by commit SHA and scans them. `deploy.sh` pulls, migrates and starts the containers, then polls health and status endpoints. If they fail, it redeploys the previous SHA. Migrations follow expand/contract: a release only adds what the previous release tolerates, so rolling the app back never needs a database downgrade. My index migration shows this: a trigger fills the new column for the old code during a rolling deploy.

**Tell me about a performance problem you found.**
I generated a year of data and timed every endpoint. `EXPLAIN ANALYZE` showed entity queries scanning all 1.09M bridge rows to find a 30-day window, so I added the article date to the bridge table with a covering index. A second, subtler problem: after five executions the driver prepares statements, and PostgreSQL switched to generic plans that couldn't use the date range or fold optional filters, making queries 2× slower in a long-running process. I fixed it with `plan_cache_mode = force_custom_plan`. I also learned to vacuum before measuring, because my first baseline was wrong. Every rewrite was checked to return identical results.

**How do you test LLM code without an API key?**
There's a deterministic fake provider for development and CI. The real SDK is tested against a local server that speaks the Messages API wire format, which covers request shape, usage parsing, cost, refusals, truncation and error mapping (401 fatal, 429/529 retried). A weekly workflow runs the real feeds and switches to the real model when a key is configured. What that can't test is output *quality*, so a manual evaluation on real articles is on the launch checklist.

**How does dedup work, and what did you get wrong first?**
Four layers: feed entry key, canonical URL, same-source headline within 48 hours, and cross-outlet near-duplicates by trigram similarity. My first threshold (0.75) merged *different* events that shared place names, while real paraphrases scored only 0.43–0.68. So near-duplicates now require ≥ 0.8 similarity **and** that the differing words are only noise such as "VIDEO" or "LIVE", with numbers counting as content. Paraphrase clustering needs embeddings; that's V2.

**What are the security considerations?**
Untrusted input everywhere: feed content (XSS, prompt injection), feed URLs (SSRF, so every redirect hop must resolve to a public IP), and query parameters (bound SQL parameters, validated ranges). Also a strict CSP, non-root read-only containers, secrets only in the environment with gitleaks in CI, and a constant-time admin-token check. The documented accepted risk is that the deploy user in the docker group is root-equivalent on a single-purpose server.

**What would you change at 100× the volume?**
Enrichment is the bottleneck and the cost driver: the Message Batches API (half price) for non-urgent work, then more concurrency. For analytics, a daily rollup table of entity × day counts. Rate limiting and caching would move from process memory to the edge or Redis once there are several API replicas. PostgreSQL itself would be fine for a long time.

**What's something you're not happy with yet?**
Source coverage is Kosovo-heavy: five verified outlets, with Albanian and North Macedonian candidates still to validate. "Unique stories" only merges near-verbatim copies. And model quality hasn't been evaluated on real articles yet, because that needs the API key.

**A bug your tests caught that would have hurt in production?**
httpx treats a `304 Not Modified` as a redirect. The fetcher would have tried to follow it, failed, and after 20 runs auto-disabled every healthy source that supports conditional GET. That's exactly the feeds you most want to keep.
