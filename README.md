# GJURMË

**See every side of the Albanian-language news.** GJURMË (*"trace, footprint"*) reads Kosovo, Albanian and North Macedonian news feeds every 15 minutes and, like [Ground News](https://ground.news/), groups the articles that report the same event into **stories**: for each story you see which outlets covered it, how their coverage splits by perspective, region, ownership and factuality, who reported it first, and how each outlet headlined it. **Blindspots** show what one side, or one country's media, barely covered, and **My news bias** shows the balance of your own reading. Underneath, Claude (or keyword rules at $0) classifies every article — topic, tone, people, organizations, places, a one-line summary — for a dashboard of what dominates coverage and who is suddenly in the news.

> **Status:** V1 is complete and tested (CI green on GitHub: lint, strict types, 300 backend tests on PostgreSQL, 53 frontend tests, 72 end-to-end browser tests, bundle budgets, security scans). **It is not deployed yet.** Deployment is scripted and rehearsed locally. It can run for **$0**: on an Oracle Cloud Always Free ARM server with a free subdomain, with keyword-rule analysis that the site discloses until a Claude API key or a [free model](docs/AI_ENRICHMENT.md#free-models) is added ([DEPLOYMENT.md](docs/DEPLOYMENT.md#oracle-cloud), [LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md)).

## What it does

- **Stories, as on Ground News.** The home page lists the news as stories, most covered first. Each story has a coverage bar (left · center · right · unrated, or by region, ownership, factuality), the outlets that covered it and who was first. The story page puts every outlet's headline side by side, linked to the original, with a timeline and related stories ([ADR-020](docs/DECISIONS.md#adr-020-stories-by-tf-idf-clustering-with-name-guards-no-embeddings)).
- **Blindspot.** Stories that left- or right-leaning outlets barely covered, and stories about a country whose own outlets did not report them.
- **Source profiles.** Each outlet's ratings and their basis, ownership, how much of the news it covers, how often it reports first, its exclusives and which outlets cover the same stories. Perspective and factuality ratings are editorial and documented in `sources.yaml`; real outlets stay *unrated* until reviewed ([ADR-021](docs/DECISIONS.md#adr-021-outlet-ratings-are-editorial-declared-with-their-basis-unrated-by-default), [how to rate](docs/SOURCES.md#ratings)).
- **My news bias.** The balance of the outlets you read here, kept only in your browser ([ADR-022](docs/DECISIONS.md#adr-022-my-news-bias-without-accounts)).
- **Made to be shared.** A story link shows its own headline and who covered it in WhatsApp, Facebook, X or Telegram, and `?lens=` keeps the chosen split ([ADR-025](docs/DECISIONS.md#adr-025-story-link-previews-for-crawlers-only)).

- **Ingests** RSS feeds from 5 verified outlets (Telegrafi, KOHA, Gazeta Express, Kallxo, Radio Evropa e Lirë) politely: robots.txt, conditional GET, per-source isolation, auto-disable on repeated failure.
- **Cleans and deduplicates** in four layers: feed entry, canonical URL, same-source headline, and cross-outlet near-verbatim copies.
- **Enriches** each headline and excerpt with Claude, using structured JSON output that is validated, repaired, and checked against the source text so the model cannot invent names. It runs under a hard daily budget with a kill switch.
- **Clusters** articles from different outlets into stories: TF-IDF over headline, excerpt and names with Albanian word folding, guards against look-alike events in different places, a 48 h span; reviewable on live data with `gjurme stories-review`.
- **Analyses:** volume with a moving average, topic momentum, entity spikes (z-scores), tone shifts, co-occurrence, source profiles, first reports, blindspots. Every method is stated next to the chart.
- **Serves** a typed FastAPI (OpenAPI docs) and an accessible, fast React site: Stories, Story, Blindspot, My news bias, Source profiles, Dashboard, Trends, Topics, Entities, Sources, Articles, About/Methodology, Status. Its architecture and every performance trade-off are measured and documented ([frontend_system.md](docs/architecture/frontend_system.md)).
- **Operates itself:** scheduler with overlap protection, 13 data-quality checks per run, webhook alerts, an external uptime monitor, nightly backups with weekly restore tests, and deploy with automatic rollback.

It stores metadata and its own analysis only. It never republishes article text, and every item links to the original ([why](docs/DECISIONS.md#adr-003-store-metadata-and-derived-data-only)).

## Architecture

```mermaid
flowchart LR
    FEEDS[(RSS feeds)] --> ING[ingest] --> RAW[(raw)] --> PROC[process + dedup] --> CORE[(core)]
    CORE --> ENR[enrich<br/>Claude · budget · validation] --> CORE
    CORE --> CLU[cluster<br/>stories] --> CORE
    CORE --> DQ[quality checks + alerts] --> OPS[(ops)]
    CORE --> API[FastAPI] --> WEB[React dashboard<br/>via Caddy · HTTPS]
```

A modular monolith: one Python package, one image running as `api` and `scheduler`, and one PostgreSQL database with `raw` / `core` / `ops` schemas. It runs on one VPS with Docker Compose. No queue, orchestrator or microservices, because the problem doesn't need them ([ARCHITECTURE.md](docs/ARCHITECTURE.md), [DECISIONS.md](docs/DECISIONS.md)).

| Layer | Stack |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, feedparser, httpx, Pydantic 2, Typer, Anthropic SDK |
| Data | PostgreSQL 16 (`pg_trgm`) |
| Frontend | React 19, TypeScript, Vite, TanStack Query, Zustand, React Router, Recharts; Newsreader headlines on the system font |
| Ops | Docker (non-root, read-only), Caddy, GitHub Actions (CI, Trivy, gitleaks, deploy), Prometheus metrics |

## Quick start (demo data, no API key)

```bash
docker compose --profile demo up --build
# open http://localhost:8080
```

This builds the images, migrates the database, seeds 45 days of **fictional** demo news (clearly labelled in the UI) — including events several fictional outlets cover with differently worded headlines, and fictional outlet ratings — through the real pipeline with the zero-cost heuristic enricher, and serves the site. For the live pipeline against real feeds, copy `.env.example` to `.env` and run `docker compose up --build`. The heuristic enricher is the default; set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` for Claude, or `LLM_PROVIDER=openai_compatible` for a free local or hosted model.

## Development

```bash
# backend (needs PostgreSQL 16)
cd backend
uv sync
export DATABASE_URL=postgresql+psycopg://gjurme:gjurme@localhost:5432/gjurme
uv run gjurme db upgrade          # migrations + source/topic registry sync
uv run gjurme demo seed --days 30 # or: uv run gjurme run   (live pipeline once)
uv run gjurme api --reload        # http://127.0.0.1:8000/api/docs

# frontend
cd frontend
npm ci
npm run dev                        # http://localhost:5173, proxies /api to :8000
```

Useful commands: `gjurme sources validate`, `gjurme run --stages ingest,process`, `gjurme enrich --limit 20`, `gjurme cluster`, `gjurme stories-review`, `gjurme quality`, `gjurme retention`, `gjurme scheduler`. Tests: [TESTING.md](docs/TESTING.md).

## Repository layout

```
backend/    gjurme package (ingestion, enrichment, stories, analytics, api, pipeline), tests, migrations
frontend/   React site (stories, blindspot, dashboard), Vitest + Playwright tests, Caddy config
deploy/     production compose, deploy/rollback script, backups, server bootstrap
docs/       blueprint, architecture, data model, AI, sources, deployment, operations,
            security, testing, decisions, launch checklist, portfolio
.github/    CI/CD, weekly source validation, uptime monitor, Dependabot
```

## Documentation

| | |
|---|---|
| [BLUEPRINT](docs/BLUEPRINT.md) | The plan: requirements, scope, architecture, roadmap |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Components, pipeline, failure behaviour, API reference |
| [FRONTEND](docs/architecture/frontend_system.md) | Frontend layers, state, performance budgets and design system, with the measurements behind each choice |
| [DATA_MODEL](docs/DATA_MODEL.md) | ERD, DDL, dedup, sample SQL, retention, migrations policy |
| [AI_ENRICHMENT](docs/AI_ENRICHMENT.md) | Prompt, schema, validation, reliability, cost model |
| [SOURCES](docs/SOURCES.md) | Verified sources with evidence; how to add one |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | Hosting, costs, step-by-step deploy |
| [NISJA](docs/NISJA.md) | Launch guide in Albanian: Claude quality test, then the free Oracle deploy |
| [OPERATIONS](docs/OPERATIONS.md) | Runbook: alerts, checks, incidents, backups, secrets |
| [SECURITY](docs/SECURITY.md) | Threats, controls, accepted risks |
| [TESTING](docs/TESTING.md) | Test strategy, failure tests, performance measurements |
| [DECISIONS](docs/DECISIONS.md) | Architecture decision records |
| [LAUNCH_CHECKLIST](docs/LAUNCH_CHECKLIST.md) | What remains before going public |
| [CHANGELOG](CHANGELOG.md) | Release notes |

## Data and attribution

Headlines and links belong to their publishers; GJURMË links every item to its original. Topic, tone, entity and summary data are machine-generated and can be wrong; story grouping is automatic; outlet ratings are editorial and state their basis. The methodology page explains how every number is produced. Publishers or people who want an item removed can use the contact on the About page ([takedown process](docs/OPERATIONS.md#takedown-request)).

## License

[MIT](LICENSE) © Florent Latifi
