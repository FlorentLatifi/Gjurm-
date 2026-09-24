# Deployment

> **Status: not deployed.** Everything below is scripted and was rehearsed locally: production compose with HTTPS, a deploy, a forced failure with automatic rollback, backup and restore. No server, domain or production credentials exist yet. The steps marked **👤 owner** need the repository owner's accounts and cannot be done from the codebase.

## Target and cost

One VPS running Docker Compose: `db` (PostgreSQL 16), `migrate` (one-shot), `api`, `scheduler`, `web` (Caddy with automatic HTTPS) and `backup` (nightly dumps, weekly restore test), plus an optional `offsite` sync. Why a single VPS and not a PaaS or Kubernetes: [ADR-007](DECISIONS.md#adr-007-single-vps--docker-compose--caddy).

| Item | Monthly | Notes |
|---|---|---|
| VPS, 2 vCPU / 2–4 GB, Ubuntu 24.04 | ≈ $12–24 | e.g. DigitalOcean Basic 2 GB ≈ $12 or 4 GB ≈ $24. Prices were checked in September 2026; **re-check before buying**. 4 GB gives comfortable headroom; 2 GB works with the swap file the bootstrap creates. |
| Domain | ≈ $1 | Any registrar; needs an A (and optionally AAAA) record. |
| Anthropic API | ≤ ≈ $60 | Hard-capped by `LLM_DAILY_BUDGET_USD=2.00` ([AI_ENRICHMENT.md](AI_ENRICHMENT.md#cost-model)). |
| Off-site backups (optional) | ≈ $0–1 | A few GB on any rclone-supported storage (S3-compatible, Backblaze B2, …). |
| GitHub Actions, GHCR | $0 | Within free allowances for a repository of this size (check your plan). |

## Environments

| Environment | How | Config |
|---|---|---|
| development | `docker compose up` (repo root) or `uv run` + `npm run dev` | `GJURME_ENV=development`, FakeProvider allowed, demo data via `--profile demo` |
| test / CI | GitHub Actions services + the same compose stack for E2E | `GJURME_ENV=test` |
| staging | the production compose on a second small server or a second DOMAIN | `GJURME_ENV=staging`: all production guards on |
| production | `deploy/docker-compose.prod.yml` | `GJURME_ENV=production` (set by the compose file) |

In staging and production the app **refuses to start** with an admin token under 32 characters, a wildcard CORS origin, the FakeProvider (unless explicitly allowed) or the default development database password (`Settings.validate_for_env`), and refuses demo seeding.

## Step by step

### 1. Server 👤 owner
Create an Ubuntu 24.04 VPS with your SSH key and note its IP. Point DNS at it: an `A` record from your chosen name (e.g. `gjurme.example.com`) to the IP, plus `AAAA` if the provider gives IPv6. Wait until `dig +short gjurme.example.com` returns the IP. Caddy needs that to obtain the certificate.

### 2. Bootstrap (as root, once)
Pin the script to a commit you have reviewed. Never pipe a moving branch into a root shell:

```bash
curl -fsSLO https://raw.githubusercontent.com/FlorentLatifi/Gjurm-/<commit-sha>/deploy/scripts/bootstrap-server.sh
less bootstrap-server.sh
bash bootstrap-server.sh
```

It installs Docker Engine from Docker's repository, creates the `deploy` user and `/opt/gjurme`, and sets up a firewall (SSH, 80, 443 only). It also disables SSH password login, enables unattended security upgrades and fail2ban, bounds Docker log sizes, and adds a 2 GB swap file if none exists.

### 3. Deploy key for CI 👤 owner
On your machine:

```bash
ssh-keygen -t ed25519 -f gjurme_deploy -C "gjurme-ci" -N ""
ssh-copy-id -i gjurme_deploy.pub deploy@<server-ip>      # or append to /home/deploy/.ssh/authorized_keys
ssh-keyscan -t ed25519 <server-ip>                         # → DEPLOY_KNOWN_HOSTS
```

### 4. Registry access 👤 owner
CI publishes `ghcr.io/florentlatifi/gjurme-api` and `gjurme-web` on every push to the default branch. If the packages are private (the default for a private repository), the server must log in once as the deploy user with a token that can read packages (a classic PAT with `read:packages`, or a fine-grained token with package read access):

```bash
sudo -iu deploy
echo "<token>" | docker login ghcr.io -u <github-username> --password-stdin
```

Alternatively, make the two packages public in GitHub → Packages → Package settings.

### 5. Configuration 👤 owner
```bash
sudo -iu deploy
cd /opt/gjurme
# copy deploy/.env.example here as .env, then:
chmod 600 .env
openssl rand -base64 36    # → POSTGRES_PASSWORD
openssl rand -base64 36    # → ADMIN_API_TOKEN
```

Fill in `DOMAIN`, `ACME_EMAIL`, the two generated secrets and `ANTHROPIC_API_KEY`. Without the key the pipeline still ingests and processes, and enrichment is skipped with a clear log line. Optionally set `ALERT_WEBHOOK_URL` / `ALERT_WEBHOOK_FORMAT`. All other variables have production defaults, documented in `backend/src/gjurme/config.py`.

### 6. First deploy
Copy the deployment files and deploy the commit whose images CI published (see the *Build, scan & publish images* job):

```bash
scp deploy/docker-compose.prod.yml deploy/scripts/deploy.sh deploy@<server>:/opt/gjurme/
scp -r deploy/backup deploy@<server>:/opt/gjurme/
ssh deploy@<server> 'cd /opt/gjurme && ./deploy.sh <full-git-sha>'
```

`deploy.sh` pulls the images, starts `db`, runs `migrate` (Alembic plus source sync) and then starts `api`, `scheduler`, `web` and `backup`. It then waits up to 120 s for `https://$DOMAIN/health/ready` **and** `/api/v1/status`, and records the tag as current. If the pull or migration fails, nothing was replaced and the running release stays. If the health check fails, it redeploys the previous tag automatically.

### 7. Continuous deployment 👤 owner
In GitHub → Settings:

| Where | Name | Value |
|---|---|---|
| Environments | `production` | Create it. Optionally add required reviewers, which makes every deploy wait for a click. |
| Environment secrets (production) | `DEPLOY_HOST` | server IP or hostname |
| | `DEPLOY_USER` | `deploy` |
| | `DEPLOY_SSH_KEY` | contents of `gjurme_deploy` (private key) |
| | `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan` |
| Repository variables | `DEPLOY_ENABLED` | `true` (the deploy job is skipped until set) |
| | `DOMAIN` | `gjurme.example.com` |
| | `PUBLIC_URL` | `https://gjurme.example.com` (enables the uptime monitor) |
| Repository secrets (optional) | `ANTHROPIC_API_KEY` | lets the weekly *Source validation* live job enrich with the real model |

From then on, every push to the default branch runs: tests → E2E → image build → Trivy scan → push to GHCR → SSH deploy → post-deploy smoke test. Images and deploy are keyed to the repository's **default branch** (currently the development branch; if you create `main` and make it the default, nothing needs to change).

### 8. Verify
```bash
curl -fsS https://$DOMAIN/health/ready
curl -fsS https://$DOMAIN/api/v1/status | jq
curl -sI https://$DOMAIN/ | grep -iE 'strict-transport|content-security'
curl -s -o /dev/null -w '%{http_code}\n' https://$DOMAIN/metrics          # expect 404
curl -fsS -H "Authorization: Bearer $ADMIN_API_TOKEN" https://$DOMAIN/api/v1/admin/runs | jq '.[0]'
ssh deploy@<server> 'cd /opt/gjurme && docker compose -f docker-compose.prod.yml ps'
ssh deploy@<server> 'cd /opt/gjurme && docker compose -f docker-compose.prod.yml run --rm backup sh /scripts/backup.sh'
```

Then run *Actions → Uptime monitor → Run workflow* once to confirm the external check passes. The full list is in [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md).

### 9. Off-site backups (optional, recommended) 👤 owner
Create a bucket and credentials at an S3-compatible provider, write `/opt/gjurme/rclone/rclone.conf` with a remote named `offsite` (see `rclone config`), and set `RCLONE_REMOTE=offsite:<bucket>` in `.env`. Then enable the profile:

```bash
docker compose -f docker-compose.prod.yml --profile offsite up -d offsite
```

## Rehearsal (what was verified locally)

With `DOMAIN=localhost`, Caddy's internal CA, and images built locally (`DEPLOY_SKIP_PULL=1`, `DEPLOY_CURL_OPTS=-k`, `COMPOSE_PROJECT_NAME=rehearsal`):

- HTTPS served; HTTP → HTTPS `308`; HSTS and the strict CSP present; `/metrics` → 404 through the edge.
- The app refused to start with an unsafe configuration (short admin token).
- `deploy.sh <tag>` succeeded. A deliberately broken release was detected by the health check and **rolled back automatically** to the previous tag.
- Backup (`pg_dump -Fc`, TOC verified), the weekly restore verification (article counts matched), and a guarded disaster-recovery restore.

## Rollback

```bash
ssh deploy@<server> 'cd /opt/gjurme && ./deploy.sh --rollback'     # previous release
ssh deploy@<server> 'cd /opt/gjurme && ./deploy.sh <older-sha>'    # any published release
```

Migrations are expand-only within a release, so rolling the application back never requires a database downgrade ([DATA_MODEL.md](DATA_MODEL.md#migrations-policy), [OPERATIONS.md](OPERATIONS.md#deploy-and-rollback)).
