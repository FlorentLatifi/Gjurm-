# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Free AI models:** `LLM_PROVIDER=openai_compatible` works with a local model (optional `ollama` container, profile `local-llm`) or a hosted free tier, with structured output, request pacing, backoff and zero pricing. A *Free model quality* workflow measures a local model on live headlines at $0 ([ADR-019](docs/DECISIONS.md#adr-019-free-models-through-an-openai-compatible-provider)).
- **Albanian launch guide** ([docs/NISJA.md](docs/NISJA.md)).
- **$0 launch path:** multi-arch images (amd64 + arm64) built natively on GitHub's free arm64 runners, and a step-by-step Oracle Cloud Always Free + DuckDNS guide ([ADR-018](docs/DECISIONS.md#adr-018-a-0-launch-path-oracle-always-free--keyword-rule-analysis)).
- **Honest rule-based mode:** `/api/v1/status` reports the analysis mode, the site shows a banner, and each article page labels its analysis as *AI* or *rule-based*. `gjurme enrich-requeue --provider fake` re-analyses rule-based results with Claude once a key is added.
- **Claude quality test:** the *Source validation* workflow takes `enrich_limit` (1–50, hard budget) and publishes a review report of every result with tokens and cost.

### Fixed
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
