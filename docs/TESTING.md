# Testing

| Layer | Tool | Count | Runs |
|---|---|---|---|
| Backend unit | pytest | 191 | CI `backend` job, locally `uv run pytest tests/unit` |
| Backend integration (real PostgreSQL 16) | pytest | 109 | CI `backend` job (Postgres service container) |
| Frontend unit / component | Vitest + Testing Library | 53 | CI `frontend` job |
| Frontend static guards | layer boundaries (ESLint), API contract (tsc), bundle budgets, colour tokens | 4 checks | CI `frontend` job |
| End-to-end (full Docker stack, demo data, real browser) | Playwright + axe-core | 36 scenarios × 2 viewports = 72 | CI `e2e` job |
| Live sources (real feeds on GitHub runners) | `gjurme` CLI in a workflow | 1 pipeline run + story clustering review | *Source validation* workflow (weekly + manual) |
| Performance (365k articles) | `backend/scripts/benchmark.py` | 19 queries | manual ([below](#performance)) |

Backend coverage gate: **85%** (currently 90%). CI on GitHub passed all four check jobs (backend, frontend, security, E2E) for the full stack, for example [run #1](https://github.com/FlorentLatifi/Gjurm-/actions/runs/36052875049).

## Running the tests

```bash
# backend: needs a PostgreSQL 16 you can create databases in
cd backend
export TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/gjurme_test
uv sync
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy
uv run pytest --cov=gjurme --cov-fail-under=85

# frontend
cd frontend
npm ci
npm run lint && npm run check:tokens && npm run check:api && npm run typecheck && npm test
npm run build && npm run check:budget

# end-to-end against the full stack
docker compose --profile demo up -d --build --wait db api web
docker compose --profile demo up demo --exit-code-from demo
cd frontend && E2E_BASE_URL=http://localhost:8080 npx playwright test
```

The integration fixtures migrate a fresh test database once per session with the real Alembic migrations, and truncate between tests. External HTTP is never called: feeds are served by a local server (`tests/conftest.py::feed_server`) and the LLM by a local fake of the Messages API (`test_anthropic_wire.py`) or the `FakeProvider`.

## What the suites cover

**Unit (191).**
- Normalization: HTML stripping, Unicode NFC, mojibake repair for `ë`/`ç`, zero-width characters, URL canonicalization and tracking parameters, date parsing including time zones, future and missing dates.
- Feed parsing: RSS/Atom, malformed XML recovery, autodiscovery.
- Fetcher: robots.txt (allow, disallow, 404 → allowed, 5xx → disallowed, caching), conditional GET/304, timeouts, oversize (declared and streamed), redirects (followed, loop, to a private address → blocked), DNS SSRF guard.
- Enrichment: schema validation and repair, the sentiment-contradiction rule, entity grounding with Albanian inflection, pricing, and budget reservations under concurrency (never overshoots).
- Alert rules and payload formats; configuration guards.
- API contract: the committed OpenAPI schema the frontend's types are generated from matches the API exactly, and response fields that are always present are declared required.
- Story similarity: Albanian folding and stemming, IDF weighting, the name guard (shared, partial and conflicting places and people; noisy entity types), "a shared person is not a shared event", and hand-written calibration pairs against the default threshold.

**Integration (109).**
- Ingest → process: idempotency (a second run creates 0 rows), per-source failure isolation, 304 handling, auto-disable after the threshold, dedup L1–L4.
- Enrichment: daily budget enforcement (including spend from earlier runs), circuit breaker, fatal errors that keep attempts, invalid output recorded and retried, refusal terminal, cache hits, re-enrichment keeping history with one current row, the kill switch, hidden articles never sent to the LLM.
- Anthropic wire: the real SDK against a fake Messages API, covering request body, usage, cost, refusal, `max_tokens`, 401/403/404 fatal, 400 non-retryable, 429/529 retried, connection failure.
- API: every public endpoint against a hand-computed dataset (counts, growth `(8 − 2) / 5`, spike `z = 6.0`), validation errors, the error envelope, admin auth, rate limiting, cache invalidation on admin mutations, security headers, `/metrics` protection, the excerpt never leaking, readiness with the DB down.
- Runner and ops: advisory-lock contention (`skipped_locked`), abandoned runs, stage crash → `failed`, all sources down → `partial` + alert, alert delivery failure recorded, retention, scheduler heartbeat and run requests.
- Migrations: `upgrade → downgrade → upgrade` with no model/migration drift; migration 0002's triggers (an old writer omits the bridge date; a date correction propagates).
- CLI: sources sync/validate and refusal of unsafe production configuration.
- Engine session settings: statement timeout, UTC, `force_custom_plan`.
- Stories: paraphrases from four outlets form one story while a look-alike fire in another town stays apart; a near-verbatim copy joins its original's story; the 48 h span; idempotency; rebuild with a new threshold; the review report; the backlog check; ratings validation and sync; the story feed's coverage counts (distinct outlets per perspective, factuality, region, ownership), filters, sorting and search; hidden articles leaving the counts; story detail (first report, entities, topics, no excerpt); perspective and region blindspots; source profiles and the "first reports" ranking; story link previews for crawlers (the story's own title and coverage, every value HTML-escaped — a hostile headline stays text — and the site card for unknown stories).

**Frontend unit (53).** Card states; the coverage bar's accessible text; story cards; the reading log (recorded only in the browser, corrupt and stale entries dropped, re-read from another tab) and the preferences store (one key that theme.js reads, hand-edited values rejected); the lens (`?lens=` wins over the remembered choice); the search box (one commit per pause, Enter, follows an outside reset); chunk-load recovery (reloads once, then explains); route prefetch (fills exactly the cache entries the page reads, skips impossible ids); previous data kept only while the *same* resource refetches; the site notice holding its line while the status loads; the placeholder summary never shown.

**End-to-end (72).** Each of the 36 scenarios runs on a desktop and a Pixel 7 viewport:
- The stories feed: coverage bars, opening a story, every outlet's headline linked to the original, first report.
- The coverage lens switches the bars, is part of the URL and is remembered; feed filters (folded behind a button on phones) are reflected in the URL; Back to the feed returns to where the reader was.
- Blindspot page and its type filter; a source profile with ratings and recent stories.
- My news bias: opening an article is recorded in the browser, shown, and cleared.
- Overview KPIs, charts and article links render without console errors.
- The time-range filter updates the URL and the numbers.
- The chart table view is accessible.
- Topic and entity drill-downs; article and people search reflected in the URL; article detail with a link to the original.
- An API failure shows an error state with retry.
- The theme persists.
- Keyboard: the skip link is the first stop, and client-side navigation moves focus.
- 404 page.
- Resilience at the edge: a page whose code fails to load reloads once and then explains, with the navigation still usable; a missing build file is a `404` with `no-store`, never the app shell; deep links revalidate (`no-cache`).
- A shared story link previews as that story for link-preview crawlers, while readers get the app.
- axe-core: no serious or critical violations on all 12 pages and on a story page.

### Failure scenarios (explicitly tested)

| Failure | Test |
|---|---|
| Feed timeout, connection error, HTTP 5xx | `test_fetcher.py::test_timeout_is_reported_not_raised`, `test_connection_error_is_reported`, `test_http_error_status` |
| Malformed XML | `test_feed_parser.py::test_malformed_feed_still_yields_entries_and_is_flagged` |
| One source broken among several | `test_ingest_process.py::test_ingest_is_idempotent_and_isolates_failures` |
| Every source down | `test_runner_ops.py::test_all_sources_down_is_partial_and_alerts` |
| Source failing repeatedly | `test_ingest_process.py::test_source_auto_disabled_after_threshold` |
| LLM invalid JSON / schema violation | `test_enrichment.py::test_invalid_output_recorded_and_retried_later`, `test_enrichment_units.py::TestSchema::test_malformed_rejected` |
| LLM refusal, auth error, rate limit, overload | `test_anthropic_wire.py` (refusal, configuration errors, 429/529), `test_enrichment.py::test_refusal_is_terminal`, `test_fatal_error_stops_immediately_and_keeps_attempts` |
| Budget exhausted (also across runs) | `test_enrichment.py::test_daily_budget_is_enforced`, `test_budget_counts_spend_from_earlier_runs` |
| Consecutive LLM failures | `test_enrichment.py::test_circuit_breaker_stops_the_stage` |
| Overlapping runs | `test_runner_ops.py::test_overlapping_run_is_skipped` (advisory lock → `skipped_locked`) |
| Process crash mid-run | `test_runner_ops.py::test_abandoned_runs_are_closed`, `test_stage_crash_marks_run_failed` |
| Database down | `test_api.py::test_ready_reports_database_down` |
| Unhandled exception in the API | `test_api.py::test_unhandled_errors_do_not_leak` |
| Alert webhook down | `test_runner_ops.py::test_dispatcher_records_delivery_failure` |
| Unsafe production config | `test_sources_cli.py::test_cli_refuses_unsafe_production_config`, `test_migrations_demo.py::test_demo_refuses_production` |
| Broken release | Rehearsed by hand: `deploy.sh` detected the failed health check and rolled back ([DEPLOYMENT.md](DEPLOYMENT.md#rehearsal-what-was-verified-locally)) |
| Lost database | Rehearsed by hand: backup → restore verification → disaster-recovery restore ([OPERATIONS.md](OPERATIONS.md#disaster-recovery-restore-over-the-live-database)) |

## Findings the tests produced

Tests found real bugs, not only regressions. The notable ones:
- httpx reports a `304 Not Modified` as a redirect. Following it would have auto-disabled every healthy source that supports conditional GET. The fetcher now checks for an actual `Location` header.
- An L2 duplicate update overwrote a stored excerpt with an empty one; excerpts are never downgraded now.
- Re-enrichment hit the cache with the article's *own* previous result; the cache now excludes it.
- On initial page load, focus management stole focus from the skip link; focus now moves only on client-side navigation.
- axe-core found a 4.49:1 contrast ratio on muted text (AA needs 4.5:1); the token was darkened.
- The E2E suite, which fans out ~8 API calls per page from one IP, tripped the original rate limits (120/min, 30/min for search). Real dashboard browsing looks the same, so the limits became 300/90 per minute. CI raises them further because a single runner plays thousands of "users".
- The first CI image build failed Trivy with 17 fixable HIGH vulnerabilities inside the official Caddy binary. Caddy is now built from source with a patched toolchain; local rescan 0, local E2E 40/40 ([ADR-017](DECISIONS.md#adr-017-build-caddy-from-source-when-upstream-lags-on-fixes)).
- A near-duplicate threshold of 0.75 merged different events that share place names. The threshold was recalibrated on real headlines ([ADR-008](DECISIONS.md#adr-008-l4-near-duplicate-rule-calibrated-on-real-headlines)).
- Caddy answered a missing `/assets/*` chunk with `index.html`, status 200, cached as `immutable` for a year — an open tab after a deploy could not recover. Deep links (`/stories/12`) got no `Cache-Control` at all. Both reproduced against a real Caddy 2.11.4 and fixed ([frontend_system.md](architecture/frontend_system.md)).
- Layout shift on a cold load measured 0.23 (desktop) and 0.33 (mobile): the demo / analysis notice arrived after the status request and pushed the page down, and the footer jumped while a page's code loaded. Now ≤ 0.002.
- Writing the API contract check found the API declaring always-present fields as optional and tone and entity types as plain strings; the schema now says what the API returns.
- A redesign that looked better was measured slower: a preloaded 47 KB interface font and React Router's data router delayed first content by ~0.45 s on a slow phone connection. Both were reverted; the numbers are below.

## Performance

**Question:** does the analytics API stay fast after a year of data at the upper design volume (1,000 articles/day)?

**Method.** `backend/scripts/benchmark.py` creates a scratch database with the real migrations. It generates 365,000 articles over 365 days (8 sources, skewed topic mix, sentiment correlated with topic), ~3 entity mentions per article with Zipf-like popularity (1,090,205 mentions, 5,000 entities), runs `ANALYZE`, then times each analytics function **as the API calls it** (production engine settings) over 9 runs.

**Environment.** PostgreSQL 16.13 with default settings (`shared_buffers` 128 MB, `work_mem` 4 MB), 4 vCPU, 15 GB RAM, so the 725 MB dataset is fully cached. A 2–4 GB VPS caches less, so expect higher numbers when data is cold. Article ids are assigned round-robin across dates in the synthetic data, which is *worse* for locality than production (ids grow with time).

**Before → after** (median / p95 in ms). Before = the code as first committed (schema 0001, default plan caching). After = migration 0002, the query rewrites and `force_custom_plan`. The rewritten queries return **identical results** on this dataset, checked with an old-vs-new comparison of every changed function.

| Query | Before median | Before p95 | After median | After p95 |
|---|---:|---:|---:|---:|
| overview 30d | 280.7 | 298.1 | 235.8 | 252.7 |
| volume 30d | 36.1 | 43.8 | 36.2 | 37.8 |
| volume 365d by topic | 116.1 | 166.7 | 118.0 | 155.2 |
| topics 30d | 39.1 | 40.1 | 36.1 | 37.6 |
| topic momentum | 11.6 | 13.3 | 9.4 | 12.2 |
| topic detail 30d | 99.2 | 112.4 | **56.5** | 63.7 |
| top entities 7d | 41.6 | 42.8 | 38.2 | 40.2 |
| top entities 30d (persons) | 124.6 | 150.8 | **84.0** | 93.1 |
| entity search 30d | 120.0 | 150.5 | **26.8** | 29.9 |
| entity spikes | 109.2 | 124.7 | **64.0** | 65.9 |
| entity detail 30d (most-mentioned entity) | 115.0 | 124.5 | **71.7** | 85.4 |
| co-occurrence 7d | 43.2 | 56.0 | 43.6 | 44.7 |
| sentiment series 30d | 21.0 | 22.0 | 21.6 | 34.4 |
| sentiment by source 30d | 20.9 | 22.0 | 20.3 | 21.0 |
| sentiment shift | 10.9 | 13.3 | 10.9 | 13.7 |
| sources compare 30d | 129.5 | 154.2 | 137.1 | 159.9 |
| articles page 1 | 19.0 | 21.5 | 16.6 | 25.2 |
| articles keyword | 14.1 | 20.2 | 13.8 | 15.3 |
| articles by entity | 66.3 | 79.3 | **34.7** | 37.5 |

**What the measurements showed, and what changed:**

1. **Generic plans.** psycopg prepares a statement after 5 executions, and PostgreSQL may then switch to a *generic* plan. A generic plan cannot fold optional filters (`CAST(:type AS text) IS NULL OR e.type = :type`) and does not know the date range. Measured on the same query: 89 ms (custom plan) vs 189 ms (generic). The 9-run benchmark only partly shows this, but a long-running API process repeats every query constantly. Fix: every connection sets `plan_cache_mode = force_custom_plan`, since re-planning costs ~1 ms.
2. **Whole-history scans.** `EXPLAIN (ANALYZE, BUFFERS)` showed windowed entity queries doing a parallel sequential scan of all 1.09M `article_entities` rows to find a 30-day window's ~90k. Migration 0002 puts the article date on the bridges with covering `(published_date, entity_id|topic_id) INCLUDE (article_id)` indexes, which turns those scans into index-only range scans.
3. **Aggregation shape.** `count(DISTINCT source_id)` forced a sort that spilled to disk; it became a two-level hash aggregate. The previous-period counts are now computed only for the page returned, not for all 5,000 entities. Spike baselines are computed only for the candidates that can qualify, and co-occurrence counts pairs on ids before joining names.
4. **Not changed:** `overview` (≈ 240 ms) is dominated by the all-entity 30-day ranking behind its "top entity" tile. `sources compare` and `volume 365d` are full-window aggregates over articles. All are cached for 2 minutes per filter combination, so a visitor rarely pays for them. The next step, if needed, is a daily rollup table (entity × day counts) refreshed by the pipeline. It is not built, because current numbers do not justify another moving part.
5. **A measurement lesson.** The first baseline was taken right after bulk loading, before `VACUUM` had set the visibility map, and it overstated the "before" times (e.g. co-occurrence 104 ms vs 43 ms after `VACUUM ANALYZE`). The table above re-measures both sides on a vacuumed database.

`work_mem` 16 MB vs 4 MB made no measurable difference, so the defaults were kept.

Re-run:
```bash
cd backend
uv run python scripts/benchmark.py --url postgresql+psycopg://postgres@127.0.0.1:5433/postgres --articles 365000 --runs 9
```

### Stories at a year of data (audit, October 2026)

The table above predates stories. The audit added 105,685 stories to the same 365k-article dataset and timed the story queries as the API calls them (best of 3–5 runs, ms). Story membership was read by joining articles on `story_id` with no date bound, so every story query scanned all of `core.articles`. A story spans at most 48 h from its first article, so members of stories dated [start, end] were published on [start, end + 2]; the queries now bound articles by `published_date` and use its index. Results are **byte-identical** before and after (JSON comparison of every changed function).

| Query | Before | After |
|---|---:|---:|
| story feed 30d (home page) | 182 | **57** |
| story feed 30d, page 3, latest | 170 | **56** |
| sources compare 30d | 527 | **136** |
| source profile 30d | 656 | **172** |
| 16 story pages (incl. related stories) | 2,121 | **314** |
| blindspots 30d | 392 | **149** |
| story feed / sources compare / source profile, 366d | 705 / 4,119 / 2,248 | unchanged (the bound covers the whole year) |

Blindspots also changed in *what* they find. They were computed in Python for the 2,000 biggest stories of the range only; over 30 days there were 4,888 candidates and the page found 81 blindspots, fewer than the 7-day page (162). The rules now run in SQL over every story in the range (the Python rule still makes the final decision): 685 blindspots for 30 days, and identical results to before for 3 and 7 days (under 2,000 candidates).

The year-long source pages stay slow (2–4 s uncached). They are cached for 2 minutes per filter, and at most `API_MAX_CONCURRENT_COMPUTATIONS` such computations run at once.

### Frontend: cold loads on a slow phone

**Method.** Chromium (Playwright) as a Pixel 7, cache disabled, 1.6 Mbit/s down, 150 ms round trip, CPU slowed 4×; the production build served by Caddy against the demo data. "Content" is the time until the first story headline (or story-page headline) is visible; median of 7 runs. *Before* is the build before the frontend overhaul, measured side by side.

| Page | Content before → after | LCP before → after | Layout shift before → after |
|---|---:|---:|---:|
| Home (stories feed) | 2412 → 2357 ms | 1840 → 1836 ms | 0.226 → 0.002 |
| A story (shared link) | 2256 → 2003 ms | 1732 → 1988 ms | 0.326 → 0.002 |
| Dashboard (charts) | 3681 → 3733 ms | 2640 → 2912 ms | 0.241 → 0.002 |

The story page's LCP moved later because its headline is set in the self-hosted serif, which swaps in after first paint; it stays inside the 2.5 s "good" threshold. Bundle sizes are guarded in CI by `npm run check:budget` (`frontend/budgets.json`).

## Accessibility testing

- Automated: axe-core via Playwright on every page, on desktop and mobile; `eslint-plugin-jsx-a11y` in CI.
- Manual checks done during development: keyboard-only navigation (skip link, focus order, focus moved on route change), visible focus, dark-mode contrast, the chart table fallbacks, and a data-viz palette validated for colour-vision deficiencies (protan/deutan/tritan) and contrast in both themes.
- Not done: testing with a screen reader by a screen-reader user.
