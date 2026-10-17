# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **One event, one story.** An article also joins a story through its closest report (cosine ≥ `STORY_MEMBER_SIMILARITY_THRESHOLD`, 0.5), since a large story's centroid is diluted by its other reports, and an article that closely matches two stories merges them, unless their places, people or numbers disagree. On the live feeds of 2026-10-17 one protest in Tirana had become three stories. A merged story's link opens the story it joined (`stories.merged_into_id`, migration 0005); `gjurme cluster` reports `stories_merged` ([ADR-020](docs/DECISIONS.md#adr-020-stories-by-tf-idf-clustering-with-name-guards-no-embeddings)).
- **AI summaries in Albanian** (prompt v1.2): the analysis writes its one-sentence summary in standard Albanian too (`summary_sq`, migration 0004), shown by the Albanian interface and leading link previews. Articles analysed before v1.2 show their English summary, marked as such, until `gjurme enrich-requeue --older-than-version v1.2`.
- **The interface in Albanian** ([ADR-026](docs/DECISIONS.md#adr-026-an-albanian-interface-by-default-english-on-request)): every page, label, chart, message and the methodology are in Albanian by default, with English one click away in the masthead (remembered in the browser). Topic names, descriptions and method notes come from the API in both languages (`name_sq`, `description_sq`, `method_sq`, `topic_name_sq`), and shared stories preview in Albanian. A test keeps the catalog complete; each page's code carries only its own text.
- **Stories, as on Ground News.** A CLUSTER stage groups the articles that report the same event into stories (TF-IDF over headline, excerpt and names with Albanian word folding and case endings; guards on the headlines' places, people and numbers against look-alike events; "a shared person is not a shared event"; a 48 h span; checked on three runs of the live feeds; [ADR-020](docs/DECISIONS.md#adr-020-stories-by-tf-idf-clustering-with-name-guards-no-embeddings)). Migration 0003 adds `core.stories` and `articles.story_id`. `gjurme cluster [--rebuild-days N]`; `gjurme stories-review` reports merged stories, weak members and near misses, and the *Source validation* workflow publishes it for the live feeds.
- **Coverage by perspective, factuality, ownership and region.** Outlets get editorial ratings in `sources.yaml` (bias, factuality, ownership, owner, and a required `ratings_note`); the real outlets stay unrated until reviewed, ownership is filled in where public ([ADR-021](docs/DECISIONS.md#adr-021-outlet-ratings-are-editorial-declared-with-their-basis-unrated-by-default), [SOURCES.md](docs/SOURCES.md#ratings)).
- **New home page and pages:** the stories feed (most covered / latest, topic, region and search filters, a coverage lens), story pages (every outlet's headline side by side, timeline, first report, coverage details, related stories), **Blindspot** (perspective and region), **source profiles** (ratings, first reports, exclusives, overlap) and **My news bias** (the balance of your reading, kept only in your browser; [ADR-022](docs/DECISIONS.md#adr-022-my-news-bias-without-accounts)). The analytics overview moves to `/dashboard`.
- **API:** `/stories`, `/stories/{id}`, `/stories/blindspots`, `/sources/{slug}`; `/sources` adds ratings, stories covered and first reports; articles carry `story_id`.
- **Quality check** `story_backlog_2h`.
- **Story link previews:** a story shared on Facebook, WhatsApp, X, Telegram or Slack previews with its own headline and who covered it. Caddy sends link-preview crawlers (only them; never search engines or readers) to `/api/share/stories/{id}` ([ADR-025](docs/DECISIONS.md#adr-025-story-link-previews-for-crawlers-only)).
- **The trace** on story pages: every report as one tick on one time line, coloured by the chosen lens, the first report marked.
- **A shared lens:** `?lens=` in the URL, so a shared link shows the split its sender chose.
- **CI guards for the frontend:** bundle budgets (`npm run check:budget`), design-token use (`check:tokens`), layer boundaries (ESLint), and a compile-time contract between the API's OpenAPI schema and the frontend's types (`check:api`, `gjurme openapi`).
- **Demo:** daily events that several fictional outlets cover with different headlines, and fictional ratings, so every feature can be explored without live data.
- **Free AI models:** `LLM_PROVIDER=openai_compatible` works with a local model (optional `ollama` container, profile `local-llm`) or a hosted free tier, with structured output, request pacing, backoff and zero pricing. A *Free model quality* workflow measures a local model on live headlines at $0 ([ADR-019](docs/DECISIONS.md#adr-019-free-models-through-an-openai-compatible-provider)).
- **Albania and North Macedonia coverage:** five more sources enabled after passing the weekly validator twice (2026-09-28, 2026-10-05): Reporter.al, Euronews Albania, BalkanWeb (AL), Portalb.mk (MK) and Reporteri.net (XK), for 10 in total. A2 CNN (404) and Kosovapress (403) stay excluded with evidence; Prishtina Insight (English) is held back until an AI model analyses articles. The keyword rules now know Albanian and North Macedonian cities, parties and the *bashkia* (municipality).
- **Albanian launch guide** ([docs/NISJA.md](docs/NISJA.md)).
- **$0 launch path:** multi-arch images (amd64 + arm64) built natively on GitHub's free arm64 runners, and a step-by-step Oracle Cloud Always Free + DuckDNS guide ([ADR-018](docs/DECISIONS.md#adr-018-a-0-launch-path-oracle-always-free--keyword-rule-analysis)).
- **Honest rule-based mode:** `/api/v1/status` reports the analysis mode, the site shows a banner, and each article page labels its analysis as *AI* or *rule-based*. `gjurme enrich-requeue --provider fake` re-analyses rule-based results with Claude once a key is added.
- **Claude quality test:** the *Source validation* workflow takes `enrich_limit` (1–50, hard budget) and publishes a review report of every result with tokens and cost.
- **Share a story** from its page: the device's share sheet on phones, otherwise copy link, WhatsApp, Viber and Facebook.
- **Story search in the masthead** on every page, leading to the feed's keyword search (`/?q=`).
- **A sitemap of the stories:** `/sitemap.xml` is built by the API (`/api/share/sitemap.xml`): the site's pages, the outlets, the topics and the stories of the last 90 days that more than one outlet covered.
- **Dead-man checks:** `HEALTHCHECK_PING_URL` is pinged after every pipeline run and `BACKUP_HEALTHCHECK_URL` after every backup, with `/fail` on failure, so an external service alerts when either stops.
- **Quality check** `feed_overflow_24h`: a fetch in which every item (5 or more) was new means items were probably missed between two polls (14 checks per run).
- **Limits on the API's work:** `API_MAX_CONCURRENT_COMPUTATIONS` (6) cache misses computed at once per process, then `503` with `Retry-After`; `DB_POOL_TIMEOUT_SECONDS` (3 s); `ENRICH_MAX_SECONDS` (600) per ENRICH stage.

### Changed
- **Unchanged API answers revalidate with `304 Not Modified`:** every public answer carries a weak `ETag`, so a returning reader's browser downloads only what changed.
- **Stories wait for the analysis:** an article is clustered once its analysis succeeded or was given up, or after `STORY_ENRICHMENT_WAIT_MINUTES` (6 h); the name guards that keep look-alike events apart read the analysis.
- **Before any outlet is rated** (the launch state), coverage is split by region: lenses with nothing to show leave the pickers, story pages say no outlet is rated yet, the Blindspot page explains the missing left/right lists and My News counts regions.
- **Faster story pages:** story queries read only the days a story can span (home feed 182 → 57 ms, story page 130 → 20 ms, source profile 656 → 172 ms at 365k articles), and blindspots are found in SQL over every story of the range, not the 2,000 biggest.
- **`/api/v1/status`** is cached for 30 s, counts with indexes (80 → 12 ms), reads "degraded" while a source is auto-disabled and "stale" when none is collected.
- **Auto-disabled sources** are fetched again every 6 h and re-enabled on success.
- **CI:** every action is pinned to a commit SHA and gitleaks to a digest (after the trivy-action tag hijack, CVE-2026-33634); the image job logs in to GHCR only after the vulnerability scan.
- **Deploys** check health through the server's own Caddy, wait until the API reports the new release and the scheduler runs, and assert the deployed commit in the CI smoke test. The API container has no internet egress and no LLM key or webhook.
- With Claude, the first call of an ENRICH run is sent alone so the rest read the cached prompt.
- IPv6 clients are rate-limited per /64.
- **Frontend rebuilt on measured architecture** ([docs/architecture/frontend_system.md](docs/architecture/frontend_system.md), [ADR-023](docs/DECISIONS.md#adr-023-a-layered-frontend-chosen-by-measurement)): layers enforced by lint; one query definition per endpoint and one query builder per page, whose requests start when a route is entered, alongside its code; Zustand for preferences and the reading record; search boxes that do not re-render the page per keystroke; Back returns to where the reader was. On a slow phone connection a shared story shows its content 0.25 s sooner, and layout shift fell from 0.23–0.33 to 0.002.
- **An editorial look** ([ADR-024](docs/DECISIONS.md#adr-024-an-editorial-identity--colour-belongs-to-data)): ink on paper for the interface, colour only for data (links no longer use the blue that means "Left"), Newsreader for headlines, a type, space and motion scale, ruled story rows with a lead story, new icons and share image. On phones the feed's filters fold behind a button.
- **API schema:** response fields that are always present are declared required, and tone and entity types are enumerated; the JSON returned is unchanged.
- **Prompt v1.1:** clearer rules for Albanian name forms, what counts as an entity, entity types, quoted speakers, tone of mixed headlines and summaries, based on the free model's mistakes on live headlines ([AI_ENRICHMENT.md](docs/AI_ENRICHMENT.md#versioning-and-reprocessing)). Analyses made with v1.0 can be redone with `gjurme enrich-requeue --older-than-version v1.1`.
- **Common nouns are no longer stored as names:** an entity with no capitalised word ("qytetarëve", "komandanti") is dropped before the grounding check and recorded as the quality flag `entities_not_proper`. On live headlines the free model listed 18 such words in 15 articles; with the filter, 4 slipped through (capitalised) and no real name was dropped. Measured results, including where v1.1 did not help a 4B model, are in [AI_ENRICHMENT.md](docs/AI_ENRICHMENT.md#versioning-and-reprocessing).

### Fixed
- Every story, outlet and topic page told search engines it was a copy of the home page (`<link rel="canonical" href="/">` in the shared `index.html`). Canonical links and `og:url` are now set per page.
- A missing story, outlet, topic, person or article showed the raw API message, and an invalid id (`/stories/abc`) loaded forever; both show a "not found" page marked `noindex`.
- A few hours without network on the server auto-disabled every source for good, and the system then reported itself healthy. A run in which 75 % or more of 3+ sources fail is treated as an outage on this side and not counted.
- One feed item with a NUL character made the whole fetch unstorable, silently; control characters are dropped and a fetch that cannot be stored is logged and counted.
- Random query parameters (`?x=<random>`) bypassed the response cache, and a client under the rate limit could exhaust the database pool; the cache key is now the endpoint's declared parameters. Unexpected errors carry the request id and security headers.
- A hand-run `gjurme enrich`/`cluster`/`process` overlapping a scheduled run failed the stage on a duplicate analysis; stage commands take the pipeline lock and a concurrent result is retried.
- Excerpts of articles whose analysis failed for good were never purged (90-day retention); `enrichment_backlog_6h` warned forever about such articles.
- Backups never ran on a bootstrapped server (the directory was not writable by the backup container's UID 70) and every failure path was silent. Backups alert first, from an exit trap, and check writability at start; `rclone sync --max-delete 4` keeps an emptied directory from wiping the off-site copy.
- Rolling back a release that added a migration failed silently; `gjurme db upgrade` now leaves a database migrated by a newer release as it is.
- `.env.example` comments after empty values became the values in Compose (`IMAGE_TAG='# leave empty…'`).
- A story listed twice on one page gave two headings the same id.
- An open tab could not recover after a deploy: Caddy answered a missing code chunk with `index.html`, cached as immutable for a year, and the app had no error boundary. Missing chunks are now a `404`, the app reloads once and otherwise explains, and the HTML of every route revalidates.
- The keyword-rule placeholder (`[headline, no AI summary] …`) was shown as a summary in article lists.
- Form control borders had 1.75:1 contrast (WCAG asks 3:1); now ≥ 3.4:1.
- Four tests started failing on runs after 8 October: the feed fixtures carry fixed September dates that PROCESS now rejects as too old. `fixture_bytes(fresh=True)` moves them forward by whole weeks.
- Keyword rules: location and organization hints written with `ë`/`ç` (*Shqipëri*, *Lëvizja*) never matched, because names are compared in folded form; the hints are now folded too.
- Manual `docker compose` commands on the server (the `dc`/`gj` aliases, backup, restore, off-site) failed with "IMAGE_TAG must be set"; they now read the running tag from `.deploy-state/current`.
- Server bootstrap no longer enables UFW on Oracle Cloud Ubuntu images, which Oracle warns can prevent boot. It opens 80/443 in Oracle's own iptables rules instead (tested for idempotency and with `iptables-restore --test`).
- The keyword-rule "summary" is labelled `[headline, no AI summary]` instead of `[demo heuristic]`.

## [1.0.0] — release candidate, not yet deployed

First complete version: pipeline, analytics, API, dashboard, operations and documentation.

### Added
- **Sources.** YAML source registry with a validator (feed check, robots.txt, field coverage, autodiscovery), run weekly on GitHub's runners. 5 verified sources enabled; 2 excluded with evidence (HTTP 403, robots.txt); 8 candidates disabled.
- **Ingestion.** Polite fetcher (robots.txt, conditional GET, identifying User-Agent, timeouts, size cap, SSRF-safe redirects) with per-source isolation and auto-disable. Raw landing tables with full fetch history.
- **Processing.** Unicode and HTML normalization (Albanian `ë`/`ç`, mojibake repair), URL canonicalization, date resolution in Europe/Tirane, validation with recorded rejection reasons, four-layer deduplication (feed entry, canonical URL, same-source headline, calibrated cross-outlet near-duplicates).
- **AI enrichment.** Claude with structured outputs, Pydantic validation plus a repair pass, entity grounding (no invented names), prompt/schema versioning, enrichment cache, a hard daily budget with thread-safe reservations, a circuit breaker, a kill switch, cost and token accounting per call, and reprocessing.
- **Analytics.** Volume with a 7-day average, topic momentum, entity spikes (z-score vs a 28-day baseline), tone and tone shift, co-occurrence, source profiles, article search. Every method is stated with its formula.
- **API.** Typed FastAPI under `/api/v1` with OpenAPI docs: public analytics, admin operations (runs, costs, pause, source control, takedown, re-enrichment, quality, alerts, failures), health, readiness, public status, Prometheus metrics. Rate limiting, response caching, security headers, request ids, a consistent error envelope.
- **Dashboard.** React/TypeScript SPA: Overview, Trends, Topics, Entities, Sources, Articles, About/Methodology, Status. URL-synced filters, chart table views, loading/empty/error states, dark mode, CVD-validated palette, keyboard and screen-reader support, SEO metadata.
- **Operations.** Scheduler with advisory-lock overlap protection and abandoned-run recovery; 12 data-quality checks per run; webhook alerts (Slack/Discord/ntfy/generic) with deduplication; retention jobs; JSON logs; external uptime, freshness and TLS monitor.
- **Delivery.** Non-root, read-only Docker images; local and production compose; Caddy with automatic HTTPS and strict CSP; nightly backups with weekly restore verification and optional off-site sync; deploy script with health check and automatic rollback; server bootstrap; CI/CD (lint, strict types, tests, E2E, gitleaks, pip-audit, npm audit, Trivy, GHCR, SSH deploy).
- **Performance.** A benchmark at one year of data (365k articles, 1.09M mentions). Migration 0002 (bridge dates with covering indexes), query rewrites and `plan_cache_mode = force_custom_plan`: entity queries 1.5–4.5× faster with identical results.
- **Documentation.** Blueprint, architecture, data model, AI enrichment, sources, deployment, operations runbook, security, testing, 17 ADRs, launch checklist, portfolio notes.

### Security
- The web image builds Caddy from source with a patched Go toolchain and dependencies (17 fixable HIGH CVEs in the upstream binary) and runs unprivileged with only `CAP_NET_BIND_SERVICE`.
- Caddy's access log truncates visitor IPs and drops `X-Forwarded-For`, so the About page's privacy statement is true. The correction/removal contact is configurable (`CONTACT_URL`), so requests need not be public GitHub issues.

[Unreleased]: https://github.com/FlorentLatifi/Gjurm-/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/FlorentLatifi/Gjurm-/releases/tag/v1.0.0
