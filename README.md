# GJURMË

**AI-powered news intelligence for Albanian-language media.** GJURMË (*"trace, footprint"*) reads Kosovo and Albanian news feeds every 15 minutes, removes duplicates, uses Claude to classify each story (topic, tone, people, organizations, places, and a one-line English summary), and turns the result into a public dashboard: what dominates coverage, who is suddenly in the news, and how outlets differ.

> **Status:** V1 is complete and tested (CI green on GitHub: lint, strict types, 219 backend tests on PostgreSQL, 23 frontend tests, 40 end-to-end browser tests, security scans). **It is not deployed yet.** Deployment is scripted and rehearsed locally. It can run for **$0**: on an Oracle Cloud Always Free ARM server with a free subdomain, with keyword-rule analysis that the site discloses until a Claude API key is added ([DEPLOYMENT.md](docs/DEPLOYMENT.md#oracle-cloud), [LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md)).

## What it does

- **Ingests** RSS feeds from 5 verified outlets (Telegrafi, KOHA, Gazeta Express, Kallxo, Radio Evropa e Lirë) politely: robots.txt, conditional GET, per-source isolation, auto-disable on repeated failure.
- **Cleans and deduplicates** in four layers: feed entry, canonical URL, same-source headline, and cross-outlet near-verbatim copies.
- **Enriches** each headline and excerpt with Claude, using structured JSON output that is validated, repaired, and checked against the source text so the model cannot invent names. It runs under a hard daily budget with a kill switch.
- **Analyses:** volume with a moving average, topic momentum, entity spikes (z-scores), tone shifts, co-occurrence, source profiles. Every method is stated next to the chart.
- **Serves** a typed FastAPI (OpenAPI docs) and an accessible React dashboard: Overview, Trends, Topics, Entities, Sources, Articles, About/Methodology, Status.
- **Operates itself:** scheduler with overlap protection, 12 data-quality checks per run, webhook alerts, an external uptime monitor, nightly backups with weekly restore tests, and deploy with automatic rollback.

It stores metadata and its own analysis only. It never republishes article text, and every item links to the original ([why](docs/DECISIONS.md#adr-003-store-metadata-and-derived-data-only)).

## Architecture

```mermaid
flowchart LR
    FEEDS[(RSS feeds)] --> ING[ingest] --> RAW[(raw)] --> PROC[process + dedup] --> CORE[(core)]
    CORE --> ENR[enrich<br/>Claude · budget · validation] --> CORE
    CORE --> DQ[quality checks + alerts] --> OPS[(ops)]
    CORE --> API[FastAPI] --> WEB[React dashboard<br/>via Caddy · HTTPS]
```

A modular monolith: one Python package, one image running as `api` and `scheduler`, and one PostgreSQL database with `raw` / `core` / `ops` schemas. It runs on one VPS with Docker Compose. No queue, orchestrator or microservices, because the problem doesn't need them ([ARCHITECTURE.md](docs/ARCHITECTURE.md), [DECISIONS.md](docs/DECISIONS.md)).

| Layer | Stack |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, feedparser, httpx, Pydantic 2, Typer, Anthropic SDK |
| Data | PostgreSQL 16 (`pg_trgm`) |
| Frontend | React 19, TypeScript, Vite, TanStack Query, Recharts, React Router |
| Ops | Docker (non-root, read-only), Caddy, GitHub Actions (CI, Trivy, gitleaks, deploy), Prometheus metrics |

## Quick start (demo data, no API key)

```bash
docker compose --profile demo up --build
# open http://localhost:8080
```

This builds the images, migrates the database, seeds 45 days of **fictional** demo news (clearly labelled in the UI) through the real pipeline with the zero-cost heuristic enricher, and serves the dashboard. For the live pipeline against real feeds, copy `.env.example` to `.env` and run `docker compose up --build`. The heuristic enricher is the default; set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` for Claude.

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

Useful commands: `gjurme sources validate`, `gjurme run --stages ingest,process`, `gjurme enrich --limit 20`, `gjurme quality`, `gjurme retention`, `gjurme scheduler`. Tests: [TESTING.md](docs/TESTING.md).

## Repository layout

```
backend/    gjurme package (ingestion, enrichment, analytics, api, pipeline), tests, migrations
frontend/   React dashboard, Vitest + Playwright tests, Caddy config
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
| [DATA_MODEL](docs/DATA_MODEL.md) | ERD, DDL, dedup, sample SQL, retention, migrations policy |
| [AI_ENRICHMENT](docs/AI_ENRICHMENT.md) | Prompt, schema, validation, reliability, cost model |
| [SOURCES](docs/SOURCES.md) | Verified sources with evidence; how to add one |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | Hosting, costs, step-by-step deploy |
| [OPERATIONS](docs/OPERATIONS.md) | Runbook: alerts, checks, incidents, backups, secrets |
| [SECURITY](docs/SECURITY.md) | Threats, controls, accepted risks |
| [TESTING](docs/TESTING.md) | Test strategy, failure tests, performance measurements |
| [DECISIONS](docs/DECISIONS.md) | Architecture decision records |
| [LAUNCH_CHECKLIST](docs/LAUNCH_CHECKLIST.md) | What remains before going public |
| [CHANGELOG](CHANGELOG.md) | Release notes |

## Data and attribution

Headlines and links belong to their publishers; GJURMË links every item to its original. Topic, tone, entity and summary data are machine-generated and can be wrong. The methodology page explains how every number is produced. Publishers or people who want an item removed can use the contact on the About page ([takedown process](docs/OPERATIONS.md#takedown-request)).

## License

[MIT](LICENSE) © Florent Latifi
