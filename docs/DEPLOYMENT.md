# Deployment

> **Status: not deployed.** Everything below is scripted and was rehearsed locally: production compose with HTTPS, a deploy, a forced failure with automatic rollback, backup and restore. No server, domain or production credentials exist yet. The steps marked **👤 owner** need the repository owner's accounts and cannot be done from the codebase.

## Target and cost

Two ways to host the same stack:

| | **Free: Oracle Cloud Always Free** ([guide below](#oracle-cloud)) | **Paid VPS** (any provider) |
|---|---|---|
| Cost | $0 (card needed only for identity verification) | ≈ $12–24/month |
| Server | ARM (Ampere A1), up to 2 OCPU / 12 GB free | x86 or ARM, 2 vCPU / 2–4 GB |
| Domain | free subdomain, e.g. `gjurme.duckdns.org` | your own domain (≈ $1/month) |
| Analysis | keyword rules ($0), labelled on the site; Claude when you add a key | Claude (budget-capped) |
| Caveats | Oracle may **stop** a VM that looks idle; capacity is sometimes unavailable | none specific |

The images are published for both `amd64` and `arm64`, so either works without changes.

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

## Oracle Cloud

The free path, as of September 2026. Oracle changes this tier: in June 2026 it halved the free Ampere allowance to **2 OCPU / 12 GB RAM**, 1,500 OCPU-hours and 9,000 GB-hours a month. Re-check the current limits on Oracle's Free Tier page before you start.

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

**4. Free subdomain 👤 owner.** At duckdns.org, sign in, create a subdomain such as `gjurme`, and set its IP to the VM's public IP. Use `DOMAIN=gjurme.duckdns.org` in `.env`. Caddy obtains the HTTPS certificate automatically on first start. DuckDNS's name servers occasionally fail lookups (SERVFAIL); Caddy retries on its own, so a delayed certificate usually resolves itself. If it keeps failing, check `IMAGE_TAG=$(cat .deploy-state/current) docker compose -f docker-compose.prod.yml logs web` in `/opt/gjurme` and the IP on duckdns.org.

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
| | `PUBLIC_URL` | `https://gjurme.example.com`. Enables the uptime monitor and is built into the SPA (canonical, Open Graph, sitemap). |
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
ssh deploy@<server> 'cd /opt/gjurme && IMAGE_TAG=$(cat .deploy-state/current) docker compose -f docker-compose.prod.yml ps'
ssh deploy@<server> 'cd /opt/gjurme && IMAGE_TAG=$(cat .deploy-state/current) docker compose -f docker-compose.prod.yml run --rm backup sh /scripts/backup.sh'
```

Then run *Actions → Uptime monitor → Run workflow* once to confirm the external check passes. The full list is in [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md).

### 9. Off-site backups (optional, recommended) 👤 owner
Create a bucket and credentials at an S3-compatible provider, write `/opt/gjurme/rclone/rclone.conf` with a remote named `offsite` (see `rclone config`), and set `RCLONE_REMOTE=offsite:<bucket>` in `.env`. Then enable the profile:

```bash
IMAGE_TAG=$(cat .deploy-state/current) docker compose -f docker-compose.prod.yml --profile offsite up -d offsite
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
