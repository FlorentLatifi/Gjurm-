# Operations runbook

Commands assume you are on the server as the `deploy` user in `/opt/gjurme`, with:

```bash
alias dc='docker compose -f docker-compose.prod.yml'
alias gj='docker compose -f docker-compose.prod.yml exec scheduler gjurme'   # CLI inside the running image
export TOKEN=$(grep ^ADMIN_API_TOKEN= .env | cut -d= -f2-)
admin() { curl -fsS -H "Authorization: Bearer $TOKEN" "https://$DOMAIN/api/v1/admin/$1" "${@:2}"; }
```

## Signals: what tells you something is wrong

| Signal | Where | Detects |
|---|---|---|
| **Uptime monitor** (GitHub Actions, every 30 min) | Failed workflow run → GitHub e-mail to the owner | Site or API down, DB unreachable, **pipeline stale** (`/api/v1/status` = `stale`: no successful run for 120 min), TLS certificate < 14 days. This is the only alarm that still works when the whole server is down. |
| **Alert webhook** (from the scheduler) | Slack / Discord / ntfy / generic JSON | Run failed, all sources down, source auto-disabled, LLM budget exhausted, LLM fatal error, circuit breaker open, data-quality failures, abnormal article volume. Deduplicated per key for 6 h; every alert (including suppressed ones) is in `ops.alert_events`. |
| `GET /api/v1/status` (public) | Browser / curl / the dashboard's Status page | `ok` / `degraded` / `stale`, last run, scheduler heartbeat, backlog, per-source health |
| `GET /health/ready` | Caddy, deploy.sh, monitor | DB reachable and migration revision |
| Docker healthchecks | `dc ps` | `db` (pg_isready), `api` (/health), `scheduler` (heartbeat ≤ 5 min old). Compose marks an unhealthy container but **does not restart it**, which is why the external monitor exists. |
| Logs | `dc logs -f --tail 200 scheduler api` | JSON lines with `run_id` (pipeline) and `request_id` (API) for correlation |
| Metrics | `/metrics`, internal only (404 through Caddy) | `gjurme_http_requests_total`, `gjurme_http_request_duration_seconds`, `gjurme_http_rate_limited_total`, `gjurme_pipeline_last_run_status`, `gjurme_pipeline_last_success_timestamp_seconds`, `gjurme_enrichment_backlog`, `gjurme_llm_cost_today_usd`, `gjurme_llm_daily_budget_usd`, `gjurme_source_active`, `gjurme_source_consecutive_failures`, `gjurme_metrics_db_up`. No Prometheus server is part of V1; the endpoint is ready for one on the internal network. |
| Slow queries | `dc logs db` | PostgreSQL logs every statement slower than 500 ms |

### Daily glance (2 minutes)

```bash
curl -fsS https://$DOMAIN/api/v1/status | jq '{status, minutes_since_success, articles_last_24h, enrichment_backlog}'
admin runs | jq '.[0:5][] | {id, status, started_at, duration_ms}'
admin costs | jq '.today'
admin quality | jq '.[] | select(.status != "pass")'
admin alerts | jq '.[0:5]'
```

## Alerts and what to do

| Alert key | Severity | Meaning | Action |
|---|---|---|---|
| `pipeline_failed` | critical | A run ended `failed` (an exception outside the per-source isolation) | `admin runs/<id>` for the error and stage errors; `dc logs scheduler`. Fix, then [trigger a run](#trigger-a-run-now). |
| `all_sources_down` | critical | 0 of N feeds fetched | Usually the server's network or DNS: `dc exec scheduler python -c "import urllib.request;print(urllib.request.urlopen('https://telegrafi.com/feed/',timeout=10).status)"`. If only this server is blocked, check the provider's status page. |
| `source_auto_disabled:<slug>` | warning | 20 consecutive failures | [Source failing](#a-source-is-failing) |
| `llm_budget_exhausted:<date>` | warning | Daily LLM budget reached; the rest waits for tomorrow | Expected on busy days. If it happens daily: raise `LLM_DAILY_BUDGET_USD`, lower volume, or switch model ([AI_ENRICHMENT.md](AI_ENRICHMENT.md#cost-controls)). |
| `llm_fatal_error` | critical | Auth or permission error, or unknown model | Check `ANTHROPIC_API_KEY` (revoked? out of credit?) and `LLM_MODEL`. Nothing was consumed; fix `.env`, `dc up -d scheduler`. |
| `llm_circuit_open` | critical | 5 consecutive LLM failures in a run | `admin failures` for the errors. Timeouts or 5xx usually mean an Anthropic incident (check status.anthropic.com); the next run retries automatically. |
| `dq:<check>` | warning | A data-quality check failed (or volume anomaly warned) | See the check table below. |

## Data-quality checks

Run after every pipeline run (and on demand: `gj quality`). Results are in `ops.data_quality_results` and at `admin quality`.

| Check | Window | Warn / fail at | Likely cause when it fires |
|---|---|---|---|
| `raw_rejection_rate_24h` | 24 h | > 10% / > 30% | A feed changed format (missing links/dates) → `admin failures` |
| `duplicate_rate_24h` | 24 h | > 95% (info) | A feed republishing old items |
| `estimated_publication_dates_24h` | 24 h | > 20% | A feed dropped or broke its dates |
| `enrichment_backlog_6h` | pending > 6 h old | > 200 / > 1000 | Budget too small, enrichment paused, or LLM failing |
| `enrichment_failure_rate_24h` | 24 h | > 10% / > 30% (critical) | LLM incident, bad key, schema problem |
| `enrichment_consistency` | all | any (critical) | `succeeded` article without a current enrichment, or the reverse (a bug) |
| `malformed_entities` | all | any | Empty or markup-like entity names (prompt or repair regression) |
| `ungrounded_entity_rate_24h` | 24 h | > 15% | The model is inventing entities: review the prompt or model |
| `source_freshness_6h` | active sources | any stale / all stale (critical) | No successful fetch in 6 h |
| `article_volume_anomaly` | 24 h vs 14-day baseline | \|z\| > 3, or 0 articles with a baseline ≥ 10 | Sources silently broken, or a real news surge |
| `foreign_domain_links_24h` | 24 h | > 5% (info) | Feed links pointing off-site (syndication, tracking redirects) |
| `low_confidence_rate_24h` | 24 h | > 30% (info) | Unusual content mix, or the model struggling |

## Runbooks

### Pipeline stale
1. `dc ps`: is `scheduler` running and healthy?
2. `dc logs --tail 200 scheduler`: look for the last `run finished` / exceptions.
3. `admin runs`: a run stuck in `running` for a long time? The next run marks it `abandoned` automatically once its lock is gone.
4. Restart: `dc restart scheduler`. It finishes a run in progress (10-minute grace) before stopping.
5. Confirm: `/api/v1/status` returns to `ok` after the next run (≤ 15 min), or [trigger a run](#trigger-a-run-now).

### Trigger a run now
```bash
admin pipeline/run -X POST          # picked up by the scheduler within ~20 s; never runs inside the API
gj run --stages ingest,process      # or directly, for specific stages (the advisory lock prevents overlap)
```

### A source is failing
1. `curl -fsS https://$DOMAIN/api/v1/status | jq '.sources[] | select(.consecutive_failures > 0)'`
2. Validate it the same way as when it was added: `gj sources validate --slug <slug>`. The report shows HTTP status, robots.txt verdict, format and fields, and any autodiscovered new feed URL.
3. If the feed moved, update `feed_url` in `sources.yaml`, commit, deploy (the migrate step syncs sources), then `gj sources enable <slug>`.
4. If the publisher now blocks automated access (403) or robots.txt disallows it, **leave it disabled**. Do not circumvent. Note it in `sources.yaml`.
5. Manual control: `gj sources disable <slug> --reason "..."` / `gj sources enable <slug>` (or the admin endpoints).

### Stop all LLM spending now
```bash
admin enrichment/pause -X POST -H 'Content-Type: application/json' -d '{"reason":"cost review"}'
admin enrichment/resume -X POST
```
It takes effect from the next enrichment stage (≤ 15 min); a batch already running finishes. For an immediate hard stop, also `dc stop scheduler` (ingestion stops too), or remove `ANTHROPIC_API_KEY` from `.env` and `dc up -d scheduler`.

### Takedown request
A publisher or person asks for an article to be removed:
```bash
admin articles/<id>/hide -X POST -H 'Content-Type: application/json' -d '{"reason":"takedown request <ref>"}'
```
The article disappears from every public endpoint immediately; cached responses expire within 2 minutes (`API_CACHE_TTL_SECONDS`). The row is kept (hidden) for the audit trail. Undo with `.../unhide`. If a publisher asks to stop being monitored altogether: `gj sources disable <slug> --reason "publisher request"`, and set `enabled: false` with a note in `sources.yaml`.

### Reprocess after a prompt or model change
Bump `PROMPT_VERSION`, deploy, then `gj enrich-requeue --older-than-version <old>`. The scheduler works through the queue within the daily budget. See [AI_ENRICHMENT.md](AI_ENRICHMENT.md#versioning-and-reprocessing).

### Deploy and rollback
- Normal path: merge to the default branch; CI deploys (tests → images → Trivy → deploy with health check and automatic rollback).
- Manual: `./deploy.sh <full-sha>`; rollback: `./deploy.sh --rollback` (previous) or `./deploy.sh <sha>`.
- `.deploy-state/current` and `.deploy-state/previous` hold the tags.
- **Migrations are expand/contract.** A release may add columns, tables, indexes and triggers that the previous release tolerates. Drops and renames wait for a later release. Therefore an application rollback never needs `alembic downgrade`. If a migration itself fails, `deploy.sh` aborts before replacing any container.

### Backups
Nightly `pg_dump -Fc` at `BACKUP_HOUR_UTC` (02:00), 7 daily + 4 weekly kept in `/opt/gjurme/backups`. Every Sunday the newest dump is restored into a scratch database and compared with the live one.

```bash
cat backups/status.json                                    # last backup result
ls -lh backups/daily backups/weekly
dc run --rm backup sh /scripts/backup.sh                   # backup now
dc run --rm backup sh /scripts/verify-restore.sh           # restore test now
```

A failed backup or restore test posts to `ALERT_WEBHOOK_URL`.

### Disaster recovery (restore over the live database)
```bash
dc stop api scheduler
dc run --rm -e CONFIRM=yes backup sh /scripts/restore.sh /backups/daily/gjurme-<stamp>.dump
dc up -d
curl -fsS https://$DOMAIN/api/v1/status | jq .status
```
`restore.sh` refuses to run without `CONFIRM=yes` and verifies the dump's table of contents first. New server: bootstrap it ([DEPLOYMENT.md](DEPLOYMENT.md)), copy `.env` and a dump (from off-site storage), `./deploy.sh <sha>`, then restore as above. The recovery point is the last nightly dump; feeds usually still hold the last ~10–30 items per source, so the next runs backfill part of the gap.

### Rotate secrets
| Secret | How | Downtime |
|---|---|---|
| `ADMIN_API_TOKEN` | new value in `.env` (`openssl rand -base64 36`) → `dc up -d api` | none |
| `ANTHROPIC_API_KEY` | create a new key in the Anthropic console, update `.env`, `dc up -d scheduler`, revoke the old key | none |
| `POSTGRES_PASSWORD` | `dc exec db psql -U gjurme -c "ALTER USER gjurme PASSWORD '<new>'"`, update `.env`, `dc up -d` | seconds |
| `ALERT_WEBHOOK_URL` | regenerate at the provider, update `.env`, `dc up -d scheduler backup`, `gj alert-test` | none |
| Deploy SSH key | new key pair; add the public key to `authorized_keys`, update `DEPLOY_SSH_KEY`, remove the old public key | none |

If a secret may have leaked, rotate first and investigate second. The token comparisons are constant-time, and secrets never appear in logs (`SecretStr`).

### Disk is filling up
`df -h; docker system df`. Usual suspects: backups (retention is by count, so check the dump size trend), Docker images (deploy.sh prunes images older than 7 days), container logs (capped at 5 × 10 MB per container). Database growth: `dc exec db psql -U gjurme -c "SELECT pg_size_pretty(pg_database_size('gjurme'))"`. Retention runs daily and purges raw payloads and excerpts; `gj retention` shows what it would purge.

### Scale up
In order: a bigger VPS (vertical scaling covers this product for a long time), a higher `ENRICH_CONCURRENCY` / budget, more uvicorn workers. At 365k articles the slowest analytics endpoint takes ~0.25 s uncached ([TESTING.md](TESTING.md#performance)), and responses are cached for 2 minutes.

## Releases and versioning

- Versions follow SemVer; the image tag is the git SHA, and release tags `vX.Y.Z` also publish `X.Y.Z` image tags.
- `CHANGELOG.md` (Keep a Changelog format) is updated in the same change as the code.
- To release: update `CHANGELOG.md`, `git tag -a v1.0.0 -m "…"`, `git push --tags`. CI builds and publishes the versioned images; deploying stays on the default branch's SHA.
- The running version is visible at `/api/v1/status` (`version`).
