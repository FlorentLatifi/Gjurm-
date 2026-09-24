# Architecture decision records

Short records of the decisions that shape the system: context, the decision, and what it costs. Newest decisions are at the end. [Deltas from the blueprint](#deltas-from-the-blueprint) lists where the implementation differs from `BLUEPRINT.md`.

---

## ADR-001: Modular monolith, one image, two processes
**Context.** One data source type, one datastore, ~1,000 articles/day at the design ceiling, one operator.
**Decision.** A single Python package (`gjurme`) with clear internal modules (ingestion, enrichment, analytics, api, pipeline). One image runs as `api` or `scheduler` (plus a one-shot `migrate`).
**Consequences.** One build, one version, one set of dependencies; shared models and no network contracts between services. The API and the pipeline still fail and restart independently. Splitting later is straightforward because stages communicate only through PostgreSQL tables.

## ADR-002: PostgreSQL is the only datastore
**Decision.** Raw, curated and operational data, the enrichment cache, runtime switches, run locks and the job state all live in PostgreSQL 16 (`raw` / `core` / `ops` schemas). Near-duplicate detection and search use `pg_trgm`. No Redis, no vector database, no object store.
**Consequences.** One thing to back up, restore and monitor. Rate-limit and API-cache state are in process memory instead (ADR-013).

## ADR-003: Store metadata and derived data only
**Context.** Publisher terms vary and were not reviewed by a lawyer; no legal claims are made.
**Decision.** Store title, URL, dates, author and categories. Use the feed excerpt only as LLM input: it is never exposed and is purged after 90 days. Publish only our own derived data (topics, entities, tone, a one-sentence English summary) with a link to the original. No page scraping, no images. Polite fetching (robots.txt, conditional GET, identifying User-Agent). A working takedown path.
**Consequences.** The product cannot show article text. Summaries are the model's own words. Sources that block automated access are excluded, not circumvented (Top Channel, Balkan Insight).

## ADR-004: No queue, no orchestrator
**Decision.** No Kafka, Celery, Airflow or Kubernetes. The pipeline is a sequence of idempotent stages that pick up their work from PostgreSQL (`processed_at IS NULL`, `enrichment_status = 'pending'`). Mutual exclusion is a `pg_try_advisory_lock`.
**Consequences.** Crash recovery is "run again". At 100× the current volume, enrichment concurrency would become the bottleneck before any queue would help.

## ADR-005: In-container scheduler, external monitor
**Decision.** `gjurme scheduler` is a long-running loop that runs every 15 min, with a heartbeat, admin run requests and daily retention. GitHub Actions cron was rejected as the scheduler: it runs best-effort (often delayed), is disabled after 60 days without activity in public repositories, and would need the database reachable from the internet. GitHub Actions is used instead as the **external** uptime and freshness monitor, the one check that still works when the server is down.
**Consequences.** A hung scheduler is detected by its Docker healthcheck (heartbeat) and by the external monitor (`status = stale`), but it is not automatically restarted (Compose does not restart unhealthy containers). Network and statement timeouts make a real hang unlikely.

## ADR-006: No date dimension
**Decision.** Dates are answered with an indexed `published_date` (Europe/Tirane) plus `generate_series` for gap filling.
**Consequences.** Fewer joins. A `dim_date` would add nothing we use (no fiscal calendars, holidays or week definitions beyond ISO).

## ADR-007: Single VPS + Docker Compose + Caddy
**Context.** Budget of tens of dollars per month; one operator; the scheduler is a long-running process.
**Decision.** One VPS (~$12–24/month) with Docker Compose. Caddy provides automatic HTTPS, static files and the reverse proxy. CI builds images to GHCR; `deploy.sh` does pull → migrate → up → health check → automatic rollback.
**Alternatives.** Render (~$20–40+ with a worker and Postgres), Fly.io (managed Postgres from ~$38), Kubernetes (no benefit at this scale).
**Consequences.** A single host is a single point of failure. That is mitigated by nightly backups with weekly restore tests, optional off-site copies, and a scripted rebuild (bootstrap + deploy + restore). The recovery point is the last nightly dump.

## ADR-008: L4 near-duplicate rule calibrated on real headlines
**Context.** The blueprint proposed trigram similarity ≥ 0.75 across outlets within 48 h.
**Measurement.** On real Albanian headlines, *different* events that share place names and boilerplate scored 0.74–0.85 (e.g. two different accidents "në Prishtinë"), while real cross-outlet rewrites of the *same* story scored only 0.43–0.68 (outlets paraphrase).
**Decision.** Mark a near-duplicate only when similarity ≥ 0.8 **and** the words that differ are noise tokens (outlet tags such as "VIDEO", "FOTO", "LIVE", "LAJM", or alphabetic words of 1–2 letters). Numbers count as content ("3 të vdekur" ≠ "5 të vdekur").
**Consequences.** L4 catches near-verbatim syndication. Paraphrased coverage of the same story stays separate: "unique stories" is conservative. Real story clustering needs embeddings (a V2 item).

## ADR-009: Text + CHECK constraints instead of ENUM types
**Decision.** Status and category columns are `varchar` with named CHECK constraints.
**Consequences.** Adding a value is one transactional migration (drop and re-create the constraint). `ALTER TYPE … ADD VALUE` has transaction restrictions and cannot remove values.

## ADR-010: Default model `claude-sonnet-5`, thinking disabled
**Context.** Short multilingual extraction and classification with a strict schema; cost scales linearly with volume.
**Decision.** `claude-sonnet-5` with `thinking: disabled`, structured outputs, a prompt-cached system prompt, and a daily hard budget. The model is configurable (`LLM_MODEL`). Models that cannot disable thinking get `effort: low`.
**Consequences.** ≈ $0.004 per article (estimated; see [AI_ENRICHMENT.md](AI_ENRICHMENT.md#cost-model)). Whether `claude-haiku-4-5` (half the price) is good enough on Albanian entities has not been evaluated; that needs an API key and is on the launch checklist.

## ADR-011: Chart colours by job, validated for colour-vision deficiency
**Decision.** Sentiment uses a diverging palette: red `#e34948` / neutral gray `#a8a79f` / blue `#2a78d6` in light mode, and `#e66767` / `#5f5e59` / `#3987e5` in dark mode, with dark-mode steps chosen separately, not flipped. Context series are gray with one accent ("emphasis" form). Every palette was run through a validator (lightness band, chroma, CVD separation ΔE, contrast). The first dark neutral (`#76756f`) failed protanopia separation and was replaced. Every chart has a text summary and a table view.
**Consequences.** Colour never carries meaning alone; red and blue remain distinguishable for common colour-vision deficiencies.

## ADR-012: Frontend toolchain pins (ESLint 9, TypeScript 5.9)
**Context.** ESLint 10 and TypeScript 7 exist.
**Decision.** Stay on ESLint 9 and TypeScript 5.9 until the ecosystem catches up. `eslint-plugin-jsx-a11y` 6.10.2 declares `eslint ≤ 9`, so `npm ci` fails with ERESOLVE on 10, and `typescript-eslint` 8.x requires `typescript < 6.1`. Dependabot ignores those majors ([`.github/dependabot.yml`](../.github/dependabot.yml)); CI proved the incompatibility on a Dependabot PR.
**Consequences.** Re-check when jsx-a11y and typescript-eslint publish support. Accessibility linting was worth more than the upgrade.

## ADR-013: In-process rate limiting and response cache
**Decision.** Token buckets per client IP and a TTL cache live in the API process (one uvicorn worker). No Redis.
**Consequences.** State resets on restart, which is acceptable for both. With several workers or replicas, the limits and the cache would be per process, and moving them to Redis or to the edge (Caddy or a CDN) would be the change.

## ADR-014: Plan every analytics query with its real parameters
**Context.** Measured: after 5 executions psycopg prepares statements, and PostgreSQL then chose generic plans that were ~2× slower for queries with optional filters ([TESTING.md](TESTING.md#performance)).
**Decision.** `SET plan_cache_mode = force_custom_plan` on every application connection.
**Consequences.** ~1 ms of planning per query in exchange for plans that use the actual date range and filters.

## ADR-015: Denormalize the article date onto the bridge tables
**Context.** Windowed entity and topic queries scanned the whole bridge history (1.09M rows at one year of data).
**Decision.** Migration 0002 copies `published_date` onto `article_entities` and `article_topics` with covering indexes. Triggers fill it for writers that omit it and propagate corrections, so the copy cannot drift.
**Consequences.** 4 bytes per bridge row plus the index, and a slightly more complex write path. Together with the query rewrites, entity queries became 1.5–4.5× faster at one year of data.

## ADR-016: Test the LLM integration without a key
**Decision.** A deterministic `FakeProvider` for development, the demo and CI. A wire-level test that runs the real SDK against a local server implementing the Messages API contract. A live workflow that switches to the real API when the `ANTHROPIC_API_KEY` secret exists.
**Consequences.** Request shape, parsing, error mapping and cost accounting are tested in CI. Output *quality* on real Albanian news is not, until a key is available.

---

## Deltas from the blueprint

| Blueprint said | Implementation | Why |
|---|---|---|
| L4 near-duplicate threshold 0.75 | 0.8 + noise-token rule | ADR-008 |
| Sources: 7 candidates including Top Channel and Balkan Insight | 5 enabled; Top Channel (403) and Balkan Insight (robots.txt) excluded; 8 new candidates disabled | Verified, not assumed ([SOURCES.md](SOURCES.md)) |
| "No successful run in 2 h" as an in-app webhook alert | Detected by the external uptime monitor through `/api/v1/status` (`stale`) | A dead scheduler cannot alert about itself |
| `gjurme enrich --reprocess --prompt-version X` | `gjurme enrich-requeue --older-than-version X`, then `gjurme enrich` (or the scheduler) | Requeueing and spending are separate steps, so the budget still applies |
| Image publishing and deploy on `main` | On the repository's default branch | The repository has no `main` branch yet |
| — | Migration 0002 (bridge dates), `force_custom_plan` | Measured performance work (ADR-014, ADR-015) |
