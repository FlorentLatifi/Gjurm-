# Deployment

> **Status: not deployed.** Everything below is scripted and was rehearsed locally: production compose with HTTPS, a deploy, a forced failure with automatic rollback, backup and restore. No server, domain or production credentials exist yet. The steps marked **👤 owner** need the repository owner's accounts and cannot be done from the codebase.

## Target and cost

Three ways to host the same application:

| | **Free, no server: Vercel + Neon + GitHub Actions** ([below](#free-hosting-without-a-server)) | **Free: Oracle Cloud Always Free** ([below](#oracle-cloud)) | **Paid VPS** (any provider) |
|---|---|---|---|
| Cost | $0, no card | $0 (card needed only for identity verification) | ≈ $12–24/month |
| Runs on | Vercel (site + API function), Neon (PostgreSQL), GitHub Actions (pipeline every 30 min, weekly backup) | ARM VM (Ampere A1), up to 2 OCPU / 12 GB free | x86 or ARM VM, 2 vCPU / 2–4 GB |
| Domain | `<project>.vercel.app`, or your own | free subdomain, e.g. `gjurme.duckdns.org` | your own domain (≈ $1/month) |
| Analysis | keyword rules ($0), labelled on the site; Claude when you add a key | same | Claude (budget-capped) |
| Caveats | 1 GB database; monthly CPU, compute-hour and transfer caps ([limits](#limits-and-what-to-watch)); Vercel Hobby is for non-commercial use | Oracle may **stop** a VM that looks idle; capacity is sometimes unavailable | none specific |

The server images are published for both `amd64` and `arm64`, so either VM works without changes.

One VPS running Docker Compose: `db` (PostgreSQL 16), `migrate` (one-shot), `api`, `scheduler`, `web` (Caddy with automatic HTTPS) and `backup` (nightly dumps, weekly restore test), plus an optional `offsite` sync. Why a single VPS and not a PaaS or Kubernetes: [ADR-007](DECISIONS.md#adr-007-single-vps--docker-compose--caddy).

| Item | Monthly | Notes |
|---|---|---|
| VPS, 2 vCPU / 2–4 GB, Ubuntu 24.04 | ≈ $12–24 | e.g. DigitalOcean Basic 2 GB ≈ $12 or 4 GB ≈ $24. Prices were checked in September 2026; **re-check before buying**. 4 GB gives comfortable headroom; 2 GB works with the swap file the bootstrap creates. |
| Domain | ≈ $1 | Any registrar; needs an A (and optionally AAAA) record. |
| Anthropic API | ≤ ≈ $60 | Hard-capped by `LLM_DAILY_BUDGET_USD=2.00` ([AI_ENRICHMENT.md](AI_ENRICHMENT.md#cost-model)). |
| Off-site backups (optional) | ≈ $0–1 | A few GB on any rclone-supported storage (S3-compatible, Backblaze B2, …). |
| GitHub Actions, GHCR | $0 | The repository is public: standard and arm64 runners are free with no minute cap. |

## Environments

| Environment | How | Config |
|---|---|---|
| development | `docker compose up` (repo root) or `uv run` + `npm run dev` | `GJURME_ENV=development`, FakeProvider allowed, demo data via `--profile demo` |
| test / CI | GitHub Actions services + the same compose stack for E2E | `GJURME_ENV=test` |
| staging | the production compose on a second small server or a second DOMAIN | `GJURME_ENV=staging`: all production guards on |
| production | `deploy/docker-compose.prod.yml` | `GJURME_ENV=production` (set by the compose file) |

In staging and production the app **refuses to start** with an admin token under 32 characters, a wildcard CORS origin, the FakeProvider (unless explicitly allowed) or the default development database password (`Settings.validate_for_env`), and refuses demo seeding.

## Free hosting without a server

Added in October 2026 for owners who cannot open an Oracle account ([ADR-027](DECISIONS.md#adr-027-a-0-path-without-a-server-vercel--neon--github-actions)). The step-by-step guide for the owner is in Albanian: [NISJA.md, part B](NISJA.md#pjesa-b-faqja-online-falas-pa-server-e-rekomanduar). All three services sign in with GitHub and need no card.

| Server component | Without a server |
|---|---|
| `web` (Caddy: static site, HTTPS, security headers, crawler previews, sitemap) | Vercel's CDN and `vercel.json` (the same headers and routing; a test keeps them equal to the Caddyfile) |
| `api` | one Vercel Python function, `api/index.py` → `gjurme.api.serverless` |
| `db` | Neon, free plan, region AWS us-east-1 (next to Vercel's `iad1` and GitHub's runners) |
| `migrate`, `scheduler` | `.github/workflows/free-hosting.yml`, started every 30 minutes by an outside cron (cron-job.org calling `workflow_dispatch`; GitHub's own schedule is the fallback): `gjurme db upgrade` + `gjurme scheduler --once` (one tick: feeds, analysis, stories, quality checks, daily retention) |
| `backup` | the same workflow, with the first run once the newest backup is 7 days old: `pg_dump` (the server's own major version), encrypted with `BACKUP_PASSPHRASE`, kept 35 days as an artifact |

**Setup, in short 👤 owner.**

1. Neon: project in *AWS US East 1*; copy the **direct** connection string (connection pooling off: no `-pooler` in the host).
2. GitHub repository secrets `DATABASE_URL` (that string) and `BACKUP_PASSPHRASE`; repository variable `FREE_HOSTING=true`; run *Actions → Free hosting → Run workflow* once.
3. Vercel (Hobby): import the repository; keep the framework preset *Other* and the root `./` (`vercel.json` holds the build); add the environment variable `DATABASE_URL`; deploy.
4. Variable `PUBLIC_URL=https://<project>.vercel.app` turns on the uptime monitor. Optional: secrets `HEALTHCHECK_PING_URL`, `ANTHROPIC_API_KEY`, `ALERT_WEBHOOK_URL`; Vercel variable `VITE_CONTACT_URL`.
5. **The clock.** A fine-grained token with *Actions: read and write* on this repository only, and a cron-job.org job that POSTs `{"ref":"<default branch>","inputs":{"task":"pipeline"}}` to `https://api.github.com/repos/<owner>/<repo>/actions/workflows/free-hosting.yml/dispatches` every 30 minutes (NISJA.md, B9). Without it the cadence is whatever GitHub's scheduler grants: every 2 to 5 hours in October 2026.

**What the function does differently.** `gjurme.api.serverless.serverless_defaults` sets what the dashboard need not: `GJURME_ENV=production`, the production domain (`VERCEL_PROJECT_PRODUCTION_URL`) as `PUBLIC_BASE_URL` and CORS origin, `TRUST_PROXY_HEADERS=true` (Vercel overwrites `X-Forwarded-For`), a pool of 1 + 2 connections per instance, and `CDN_CACHE_SECONDS=300`: public API answers and the sitemap carry `CDN-Cache-Control`, so Vercel's CDN serves repeat requests for five minutes without calling the function or waking the database. Link-preview pages never do: a crawler's preview and a reader's app share the URL `/stories/{id}`, and a cache keyed by URL must never hold the preview. Without `ADMIN_API_TOKEN` in Vercel's environment the admin API is closed (a random token nobody knows). `vercel.json` sends the requested path along as `?__path=`, so the app sees the original path whichever path Vercel hands the function. If `DATABASE_URL_UNPOOLED` is set (the Neon integration sets it next to a pooled `DATABASE_URL`), it wins: the pipeline's advisory lock and the session settings need a direct connection. The front end takes its public URL from the same Vercel variable at build time (robots.txt, og:image, canonical and shared links).

**Not available without a server:** Prometheus `/metrics`, the weekly restore test of the backup, and the scheduler's 15-minute cadence (30 minutes here, kept by the outside cron; a run from a GitHub runner talks to Neon over ~100 ms round trips, so a tick takes 1 to 4 minutes, longer after a gap).

### Limits and what to watch

Free-plan figures as published in October 2026; GJURMË's figures are estimates for the first months, at about 600–1,000 articles a day.

| Service | Free plan | GJURMË (estimate) | At the cap |
|---|---|---|---|
| Neon storage | 1 GB per project | grows ≈ 250–400 MB/month at first with 19 sources; retention is shortened to 7 days (raw feed payloads) and 30 days (excerpts) | writes fail |
| Neon compute | 100 CU-hours/month, scale to zero after 5 min idle | ≈ 45 CU-hours for the pipeline (48 wake-ups a day), plus readers' cache misses | compute suspended until the next month |
| Neon transfer | 5 GB/month | ≈ 2–3 GB (mostly the clustering stage reloading four days of headlines, names and the first words of each excerpt per run) | compute suspended until the next month |
| Vercel Hobby | 4 h active CPU, 1 M invocations, 100 GB transfer per month; non-commercial use only | a cold start costs ≈ 0.8 s CPU (the API no longer imports the LLM SDKs at start-up); answers served from the CDN cost nothing | project paused until the next month |
| GitHub Actions | unlimited for a public repository | 48 runs a day, ≈ 1–3 minutes each | — |

The `database_size` quality check measures the database against `DB_SIZE_LIMIT_MB` (1024 in the workflow) and warns at 80 %, which also raises an alert. The uptime monitor runs a few minutes after each pipeline run, while Neon is still awake. When a cap comes close: Neon's *Launch* plan is pay-as-you-go (no minimum), or move to a server: restore the latest weekly backup there with `pg_restore` (below), then follow the Oracle or VPS path.

**Backups and restore.** *Actions → Free hosting* → a Sunday run → *Artifacts*; or *Run workflow → task: backup* at any time. Neon also keeps 6 hours of history (instant restore).

```bash
gpg -d gjurme-YYYY-MM-DD.dump.gpg > gjurme.dump     # asks for BACKUP_PASSPHRASE
pg_restore --clean --if-exists --no-owner --dbname "postgresql://…" gjurme.dump
```

**Scheduled runs and the 60-day rule.** GitHub disables scheduled workflows in a public repository after 60 days without activity. The workflow re-enables itself every Sunday (`keepalive` job); if it is ever disabled anyway, *Actions → Free hosting → Enable workflow*.

## Oracle Cloud

The free path with a server, as of September 2026. Oracle changes this tier: in June 2026 it halved the free Ampere allowance to **2 OCPU / 12 GB RAM**, 1,500 OCPU-hours and 9,000 GB-hours a month. Re-check the current limits on Oracle's Free Tier page before you start.

**1. Account 👤 owner.** Sign up at oracle.com/cloud/free. Oracle requires a phone number and a **credit or debit card for identity verification only**: a temporary $1 authorization, no charge unless you upgrade. Prepaid, virtual and PIN-debit cards are refused. Choose your **home region** carefully, because Always Free VMs can only be created there. Frankfurt or another European region is close to the audience.

**2. VM 👤 owner.** *Compute → Instances → Create instance*:
- Image: **Canonical Ubuntu 24.04**. Shape: **VM.Standard.A1.Flex** (Ampere) with **1 OCPU and 4 GB**. The whole stack measured about 330 MB of RAM locally with demo data (API 104 MB, scheduler 115 MB, PostgreSQL 97 MB, Caddy 12 MB); PostgreSQL grows with the data. So 4 GB is plenty and leaves half the free allowance unused.
- Networking: create a VCN with a public subnet and **assign a public IPv4 address**.
- SSH keys: paste your public key.
- If you see "Out of capacity", retry later or choose another availability domain. It is a known limitation of the free Ampere pool.

**3. Open ports in Oracle's network firewall 👤 owner.** *Networking → Virtual cloud networks → your VCN → Security Lists → Default → Add ingress rules*, each with source `0.0.0.0/0`:
- TCP destination port **80**, needed for the HTTPS certificate challenge and the redirect;
- TCP destination port **443**;
- UDP destination port **443** (optional, HTTP/3).

Port 22 is open by default. The VM has a second firewall (iptables) that the bootstrap script opens in step 5.

**4. Free subdomain 👤 owner.** At duckdns.org, sign in, create a subdomain such as `gjurme`, and set its IP to the VM's public IP. Use `DOMAIN=gjurme.duckdns.org` in `.env`. Caddy obtains the HTTPS certificate automatically on first start. DuckDNS's name servers occasionally fail lookups (SERVFAIL); Caddy retries on its own, so a delayed certificate usually resolves itself. If it keeps failing, check `IMAGE_TAG=$(cat .deploy-state/running) docker compose -f docker-compose.prod.yml logs web` in `/opt/gjurme` and the IP on duckdns.org.

**5. Bootstrap.** SSH in as `ubuntu`, then run the script as root (`sudo -i`), as in [step 2 below](#2-bootstrap-as-root-once). It detects Oracle's Ubuntu image and **does not enable UFW**, which Oracle warns can stop an instance from booting. Instead it adds ACCEPT rules for 80/443 to Oracle's own `/etc/iptables/rules.v4`, before its REJECT rule, and keeps a copy as `rules.v4.pre-gjurme`.

**6. Registry access.** The repository is public, so the simplest option is to make the two GHCR packages public (GitHub → your profile → Packages → `gjurme-api` / `gjurme-web` → Package settings → Change visibility). The server then needs no token. Otherwise follow [step 4 below](#4-registry-access--owner).

**7. Configure and deploy.** Continue with [steps 3–8 below](#3-deploy-key-for-ci--owner). In `.env`, keep the free analysis mode (`LLM_PROVIDER=fake` with `ALLOW_FAKE_LLM_IN_PRODUCTION=true`, see `deploy/.env.example`). The site then shows a banner that topics, tone and names come from keyword rules.

**8. Keeping the VM running.** Oracle may **stop** an Always Free VM whose CPU (95th percentile), network *and* memory use all stay under 20% for 7 days. This app is light enough to qualify, and it cannot be kept above those thresholds honestly. Two options:
- **Stay free-only.** If Oracle stops the VM, the external uptime monitor (GitHub Actions) e-mails you. Start the VM again from the console; the disk and the data are kept.
- **Convert the account to Pay-As-You-Go** (*Billing → Upgrade*). Oracle does not stop idle resources on PAYG accounts, and Always Free resources stay free. The card becomes chargeable **if you exceed** the free limits, so first create a budget with an alert at $1 (*Billing → Budgets*).

Everything else (backups, alerts, rollback, runbook) works the same as on a paid VPS.

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

`deploy.sh` pulls the images (including `db` and `backup`, so PostgreSQL gets minor updates), starts `db`, runs `migrate` (Alembic plus source sync) and then starts `api`, `scheduler`, `web` and `backup`. It then waits up to 120 s until this server's Caddy answers `/health/ready` **and** `/api/v1/status` reports the new tag as its `version` and the scheduler is running (it asks Caddy on 127.0.0.1, so a DuckDNS lookup failure cannot fail a healthy release), and records the tag as current. `.deploy-state/running` always holds the tag whose containers are up, healthy or not; use it in `IMAGE_TAG=$(cat .deploy-state/running) docker compose …`. If the pull or migration fails, nothing was replaced and the running release stays. If the health check fails, it redeploys the previous tag automatically; the previous release's `db upgrade` leaves a database that a newer release migrated as it is (migrations are expand-only). Old images are pruned after a week.

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
| | `PUBLIC_URL` | `https://gjurme.example.com`. Enables the uptime monitor and is built into the SPA (canonical links, Open Graph, robots.txt). The sitemap is built by the API from `DOMAIN`. |
| | `CONTACT_URL` | `mailto:…` for correction/removal requests on the About page. The default is public GitHub issues. |
| Repository secrets (optional) | `ANTHROPIC_API_KEY` | lets the weekly *Source validation* live job enrich with the real model |

From then on, every push to the default branch runs: tests → E2E → image build → Trivy scan → push to GHCR → SSH deploy → post-deploy smoke test. Images and deploy are keyed to the repository's **default branch** (currently the development branch; if you create `main` and make it the default, nothing needs to change).

### 8. Verify
```bash
curl -fsS https://$DOMAIN/health/ready
curl -fsS https://$DOMAIN/api/v1/status | jq
curl -sI https://$DOMAIN/ | grep -iE 'strict-transport|content-security'
curl -s -o /dev/null -w '%{http_code}\n' https://$DOMAIN/metrics          # expect 404
curl -fsS -H "Authorization: Bearer $ADMIN_API_TOKEN" https://$DOMAIN/api/v1/admin/runs | jq '.[0]'
ssh deploy@<server> 'cd /opt/gjurme && IMAGE_TAG=$(cat .deploy-state/running) docker compose -f docker-compose.prod.yml ps'
ssh deploy@<server> 'cd /opt/gjurme && IMAGE_TAG=$(cat .deploy-state/running) docker compose -f docker-compose.prod.yml run --rm backup sh /scripts/backup.sh'
```

Then run *Actions → Uptime monitor → Run workflow* once to confirm the external check passes. The full list is in [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md).

**Dead-man checks (recommended, free).** GitHub stops scheduled workflows in a repository without activity for 60 days, and the uptime monitor cannot tell whether backups run. At healthchecks.io (or similar) create two checks: *pipeline* (period 15 min, grace 1 h) and *backup* (period 1 day, grace 2 h). Put their ping URLs in `.env` as `HEALTHCHECK_PING_URL` and `BACKUP_HEALTHCHECK_URL` and redeploy: every pipeline run and every backup pings, with `/fail` on failure, and the service alerts when pings stop.

**Servers set up before October 2026.** The bootstrap script used to create `backups/` owned by the deploy user, which the backup container (UID 70) cannot write, so no backup ever ran. `deploy.sh` warns about it; fix it once with `sudo chown 70:70 /opt/gjurme/backups && sudo chmod 700 /opt/gjurme/backups && sudo chmod 755 /opt/gjurme/backup`.

### 9. Off-site backups (optional, recommended) 👤 owner
Create a bucket and credentials at an S3-compatible provider, write `/opt/gjurme/rclone/rclone.conf` with a remote named `offsite` (see `rclone config`), and set `RCLONE_REMOTE=offsite:<bucket>` in `.env`. Then enable the profile:

```bash
IMAGE_TAG=$(cat .deploy-state/running) docker compose -f docker-compose.prod.yml --profile offsite up -d backup-offsite
```

## Rehearsal (what was verified locally)

With `DOMAIN=localhost`, Caddy's internal CA, and images built locally (`DEPLOY_SKIP_PULL=1`, `DEPLOY_CURL_OPTS=-k`, `COMPOSE_PROJECT_NAME=rehearsal`; build the API image with `--build-arg VERSION=<tag>`, since the health check now expects `/api/v1/status` to report the deployed tag):

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
