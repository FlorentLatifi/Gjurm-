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
**Consequences.** L4 catches near-verbatim syndication. Paraphrased coverage of the same story stays separate: "unique stories" is conservative. Grouping paraphrases into stories is a separate stage with a different method ([ADR-020](#adr-020-stories-by-tf-idf-clustering-with-name-guards-no-embeddings)).

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

## ADR-017: Build Caddy from source when upstream lags on fixes
**Context.** The first image build on CI failed Trivy: the official `caddy:2-alpine` (v2.11.4, the latest release) ships a binary built with Go 1.26.3 and older `golang.org/x/crypto`, `x/net`, `x/text` and gRPC. That is 17 HIGH findings, all with fixed versions available. The same scan reproduced locally.
**Decision.** The web image builds the *same* Caddy release in a `golang:1.26-alpine` stage (Go 1.26.8) with the fixed module versions pinned (`go get …@version`), and copies the binary into the official image layout. The scan gate was not weakened: no `.trivyignore`, no severity change. The image also now runs as an unprivileged user with only `cap_net_bind_service`.
**Consequences.** Local Trivy: 17 → 0 fixable HIGH/CRITICAL. Local full-stack E2E passes (40/40), and HTTPS with certificate storage works as the unprivileged user. Costs about a minute of build time. The pins must be revisited on each Caddy release and dropped once upstream includes the fixes.

## ADR-018: A $0 launch path (Oracle Always Free + keyword-rule analysis)
**Context.** The owner does not want to pay anything yet. The API is the only component with no free tier. Anthropic gives new accounts a small one-time trial credit (widely reported as ≈ $5; not an official figure). Hosting options checked in September 2026: Render's free Postgres expires after 30 days and its web services sleep; Neon's free Postgres is 0.5 GB; Oracle's Always Free Ampere VMs (2 OCPU / 12 GB since June 2026) run the whole stack unchanged but require a card for verification and may stop VMs that look idle.
**Decision.** Launch on an Oracle Always Free ARM VM with a free DuckDNS subdomain, and publish multi-arch images (native arm64 builds on GitHub's free arm64 runners). Analyse articles with the existing keyword-rule provider, and **disclose it**: `/api/v1/status` reports the analysis mode, the site shows a banner, and every article page labels its analysis method. Use the one-time Claude credit for a quality test through the *Source validation* workflow (1–50 articles, hard budget). Switching to Claude later is configuration plus one command (`gjurme enrich-requeue --provider fake`).
**Consequences.** $0 running cost with the same architecture, backups and operations as a paid VPS. Analysis quality is low until Claude is enabled, and the site says so. The bootstrap had to learn Oracle's firewall convention: iptables `rules.v4` instead of UFW, which Oracle warns can break boot. The owner chooses between accepting an occasional idle stop and converting to Pay-As-You-Go with a budget alert.

## ADR-019: Free models through an OpenAI-compatible provider
**Context.** The owner wants AI analysis without paying, while keeping the option to move to Claude. Claude has no free tier. Open-weight models can run on the free Oracle VM (CPU only), and several hosted APIs have free tiers; almost all of them speak the OpenAI `/chat/completions` format.
**Decision.** One `OpenAICompatibleProvider` (plain `httpx`, no extra SDK) behind the existing provider protocol: JSON-schema structured output with `json_object` and prompt-only fallbacks, temperature 0, request pacing and `Retry-After`-aware retries for free tiers, configurable per-token prices (0 by default) that cannot override known Claude prices. An optional `ollama` container in the production compose file (profile `local-llm`, internal network to the scheduler, egress only for model downloads). A $0 workflow measures a local model's quality on live headlines with the same report as the Claude test.
**Consequences.** Switching between rules, a free model and Claude is configuration plus a re-analysis command; nothing else changes. A local model on 1–2 ARM cores is slow and weaker in Albanian, so its quality must be measured before it replaces the rules. With a price of 0 the daily budget no longer limits volume; `ENRICH_MAX_PER_RUN` and the pacing do. The `ollama` image is not pinned to a version, unlike the application images.

## ADR-020: Stories by TF-IDF clustering with name guards, no embeddings
**Context.** The product now follows Ground News: articles of different outlets that report one event form a *story*, and each story shows who covered it. ADR-008 measured that headline trigram similarity cannot do this on Albanian news: paraphrases of one event score 0.43–0.68, different events that share a place name 0.74–0.85. Embedding models would work but cost money or a GPU, and the site must run for $0.
**Decision.** A CLUSTER stage after ENRICH, single pass in publication order:
- **Vectors:** TF-IDF over headline (weight 2), the first 40 words of the feed excerpt (1) and the analysis' entity names (1). Words are folded (ë → e), stopwords and outlet labels dropped, and stemmed by truncating to six letters and dropping one Albanian case ending (Kurti/Kurtin/Kurtit → *kurt*, Prizren/Prizrenit → *prizr*); truncating first keeps long words apart (presidenti/presioni). IDF comes from the articles of the same few days (the batch ± 48 h).
- **Join rule:** an article joins the story with the highest centroid cosine ≥ `STORY_SIMILARITY_THRESHOLD` (0.45), if (1) the whole story still spans ≤ 48 h; (2) the article's *headline* shares a word with the story that is not part of a person's name; and (3) the *headlines'* names and numbers do not conflict: specific places, and numbers of two or more digits ("12 të vrarë", "14 për qind"), must be at least half shared on the smaller side; people need one in common; country-level places are ignored, and a word typed as a place anywhere in the same days counts as a place everywhere (keyword rules swallow towns into "Spitali i Tiranës"). Near-verbatim copies (L4) join their original's story directly.
- **Wait for the analysis:** the place and person guards read the analysis' entities, so an article is clustered once its analysis is done, or after `STORY_ENRICHMENT_WAIT_MINUTES` (6 h) without one (budget spent, kill switch). An article clustered without entities takes as places the headline words that any analysis has typed as a place. Before this, an article clustered while its analysis was pending had no names to compare, and look-alike events ("Zjarr në Prizren" / "Zjarr në Gjakovë") merged, permanently.
- **Stability:** assignments are never revisited, so story URLs stay valid; `gjurme cluster --rebuild-days N` re-clusters after a threshold change.
- **Calibration:** 23 hand-written pairs (12 paraphrases of one event, 11 look-alike different events), the demo, and three runs on the live feeds. At 0.45 (IDF from a week of demo headlines): 7/12 paraphrases join, 9/11 different events stay apart — look-alikes score *higher* than paraphrases and only the guards separate them. The two that merge are "X meets Y" / "X meets Z" on the same day, the known limitation.
- **What the reviews changed.** Each failure mode was found with `gjurme stories-review` and fixed: a person new to the news (a rare, heavy name) pulled unrelated stories together (rule 2); a rolling window chained two dialogue rounds four days apart (rule 1 is a fixed span); short names kept their case endings, "Kurtin" ≠ "Kurtit" (stemming); on live feeds, names from excerpts split real stories — keyword rules typed "Gazeta Online Reporteri" (boilerplate in every excerpt of one outlet) and "Shtetet e Bashkuara" as people, and outlets quote different people (guards use headline names only; people need one in common); demo template headlines differing only in a percentage merged (number guard); a town hidden inside an organisation's name ("Spitali i Tiranës") escaped the place guard (place lexicon); a town shared only through an excerpt let unrelated stories merge (rule 2 reads the headline).
- **Live feeds (2026-10-11, 123 articles from 8 outlets, keyword-rule entities):** with the final rules, 13 multi-outlet stories, all correct on inspection (the Riyadh airport attack, Messi and the Roth–Dačić meeting from three outlets each; hurricane Isaias, the Bulgarian prime minister congratulating Kurti, the US offer to Russia, the Partizani–Tirana derby, …). The first run, before the headline-only guards, found 8, also correct, and missed the Riyadh attack, Isaias and a weather forecast; the remaining near misses are kept apart only by the threshold.
- **Checking on real data:** `gjurme stories-review` lists multi-outlet stories, the weakest member of each and the closest near misses; the *Source validation* workflow publishes it for the live feeds.
**Consequences.** Precision over recall, like L4: a wrong merge would misstate coverage, a missed merge only makes a story look less covered. Some paraphrases stay separate stories, and stories about a recurring event older than 48 h start again. Counts and coverage are computed from the visible member articles at query time, so takedowns and rating changes apply at once. An embedding model behind the same stage remains the upgrade path.

## ADR-021: Outlet ratings are editorial, declared with their basis, unrated by default
**Context.** Ground News splits coverage by the outlets' political bias, factuality and ownership, using ratings from AllSides, Ad Fontes Media and Media Bias/Fact Check. No such ratings exist for Albanian-language outlets, and Kosovo and Albanian media are not usefully described by a US left–right axis without a careful review.
**Decision.** `sources.yaml` declares per outlet `bias` (left · lean left · center · lean right · right), `factuality`, `ownership`, `owner` and `ratings_note`. A bias or factuality rating is rejected by the registry without a `ratings_note` saying what it is based on. The software never infers a rating. The real outlets ship **unrated**; ownership is filled in only where it is public (the BIRN newsrooms, RFE/RL, private portals). The demo's fictional outlets carry fictional ratings so every feature can be explored. Two dimensions need no judgement and work from day one: **region** (the outlet's country) and ownership.
**Consequences.** Until the operator documents ratings, perspective bars show "unrated" and the feed defaults to the region lens; perspective blindspots need at least three *rated* outlets. Region blindspots ("a story about Albania that no Albanian outlet covered") work immediately. The labels are a five-point left–right scale as on Ground News; a different axis (e.g. towards the government) would be a relabelling in `frontend/src/shared/model/ratings.ts` plus a documented review.

## ADR-022: "My news bias" without accounts
**Decision.** The reading balance (Ground News' *My News Bias*) is computed in the browser from a local record of the outlets of articles opened on GJURMË: `localStorage`, at most 500 entries and 90 days, clearable, never sent to the server. No accounts, no cookies, no tracking.
**Consequences.** The record is per browser and lost with site data. In return there is no personal data to protect, and the privacy statement stays true.


## ADR-023: A layered frontend, chosen by measurement
**Context.** The frontend grew page by page: one global stylesheet, three hand-written persistence patterns, filters re-rendering whole pages on each keystroke, no error boundary, and an edge config that answered a missing chunk with the app shell cached for a year. The full audit, with measured bundle sizes, is [architecture/frontend_system.md](architecture/frontend_system.md).
**Decision.** Layers `app → features → ui / stores / shared → design`, enforced by ESLint import rules. Four homes for state: server data in TanStack Query (one query definition per endpoint, freshness per kind of data), what defines the view in the URL (including the coverage lens), per-browser preferences and the reading record in Zustand, and ephemeral input in the component. Each page has one pure function that turns its URL into its queries; the router starts those requests the moment a route is entered, alongside the page's code. Every change was measured on a slow phone connection against the previous build, and two that measured worse were reverted: React Router's data router (+13 KB on every page, net slower) gave way to `BrowserRouter` with the same prefetch, and a preloaded interface font (−370 ms to first content) gave way to the system font.
**Consequences.** First content on a cold story link is 0.25 s sooner and layout shift fell from 0.23–0.33 to 0.002; the entry bundle is 103 KB gzipped (was 99 KB). CI guards what was measured: bundle budgets, layer boundaries, design tokens, and a compile-time contract between the API's OpenAPI schema and the frontend's types (which found real drift on its first run). A new page needs its query builder and a route entry, not a new pattern.

## ADR-024: An editorial identity — colour belongs to data
**Context.** The interface used the same blue for links, focus and the active tab as for "Left" in the coverage bars; on a site about bias, every link read as left-leaning. The look was a generic dashboard: system font, rounded shadowed cards, 22 font sizes.
**Decision.** Ink on paper for everything that is not data (links, focus, navigation, controls; control borders ≥ 3:1). Colour only in data marks, which stay on the surface their palettes were validated for (ADR-011). Perspective keeps Ground News' blue / gray / red, because the product follows Ground News and its readers already read that convention. Headlines in Newsreader (self-hosted, 38 KB with Albanian and Serbian letters); the interface in the reader's system font. Tokens for type (7 sizes, 2 weights), space (4 px grid), radius and motion (nothing animates on load; reduced motion stops everything). The signature is the trace: every report of a story as one tick on one time line.
**Consequences.** Colour on screen always means something. One interface font fewer means the identity rests on the headline face and the layout; an attempt with a custom interface face (Atkinson Hyperlegible, then Schibsted Grotesk) was dropped — the first draws a slashed zero in every date, the second cost 370 ms on slow connections.

## ADR-025: Story link previews for crawlers only
**Context.** A single-page app serves one `index.html`, so a story shared on Facebook, WhatsApp, X, Telegram or Slack previewed as the home page — the main way news travels in the region.
**Decision.** Caddy sends known link-preview crawlers, by User-Agent, for `/stories/{id}` to `/api/share/stories/{id}`: a static HTML page with the story's own title, who covered it (and the AI summary when there is one), canonical URL and image, and a redirect to the real page. Search engines and readers always get the app: no cloaking.
**Consequences.** Shared stories show what they are. The page carries metadata only (ADR-003), escapes every value and sends the API's strict CSP. A crawler not on the list gets the generic card, which is the previous behaviour.

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
| Story clustering with embeddings in V2 | TF-IDF clustering with name guards (CLUSTER stage, migration 0003), stories as the home page | Ground News-style product at $0 (ADR-020–022) |
| Frontend: React Router data router, CSS Modules, a custom interface font ([frontend_system.md](architecture/frontend_system.md) §1–4) | `BrowserRouter` with route prefetch, one stylesheet per component, the system font for the interface | Measured slower or not worth the churn (ADR-023, ADR-024) |
