# Launch checklist

Legend: ✅ done and verified (evidence linked) · 👤 needs the owner (accounts, money, or a judgement call) · ⬜ to do at launch.

## 1. Built and verified

| | Item | Evidence |
|---|---|---|
| ✅ | Pipeline: ingest → process → enrich → quality → alerts | 219 backend tests incl. 93 against PostgreSQL ([TESTING.md](TESTING.md)) |
| ✅ | Real sources work | [Source validation run](https://github.com/FlorentLatifi/Gjurm-/actions/runs/36046867715): 5 feeds verified, 91 live articles, 0 rejects |
| ✅ | Claude integration (request shape, parsing, errors, cost) | Wire-level tests with the real SDK. **Output quality on real articles not yet evaluated** (needs a key, see 3.1). |
| ✅ | Dashboard works and is accessible | 40 Playwright tests incl. axe-core on every page, desktop and mobile |
| ✅ | CI green on GitHub | Backend, frontend, security and E2E jobs ([CI runs](https://github.com/FlorentLatifi/Gjurm-/actions/workflows/ci.yml)) |
| ✅ | Production stack, HTTPS, headers, rollback | Local rehearsal ([DEPLOYMENT.md](DEPLOYMENT.md#rehearsal-what-was-verified-locally)) |
| ✅ | Backups restore | Backup → restore verification (counts match) → disaster-recovery restore, rehearsed |
| ✅ | Performance at one year of data | [TESTING.md#performance](TESTING.md#performance): slowest endpoint ≈ 0.24 s uncached |
| ✅ | Images build and pass Trivy | Caddy rebuilt from source (ADR-017); both images passed and were pushed to GHCR ([run 11](https://github.com/FlorentLatifi/Gjurm-/actions/runs/36059125970)). Multi-arch (amd64 + arm64) builds added for the free Oracle path. |
| ✅ | Free mode is honest | Rule-based analysis is disclosed in `/api/v1/status`, a site banner and every article page (backend and frontend tests) |

## 2. Owner actions (cannot be done from the codebase) 👤

### The $0 path (chosen): Oracle Always Free + DuckDNS + keyword-rule analysis ([ADR-018](DECISIONS.md#adr-018-a-0-launch-path-oracle-always-free--keyword-rule-analysis))

| | Action | Where |
|---|---|---|
| 👤 | **Claude quality test with the trial credit:** create an Anthropic API key (console.anthropic.com; new accounts get a small one-time credit after phone verification, reportedly ≈ $5), add it as the repository secret `ANTHROPIC_API_KEY`, then ask for the *Source validation* workflow to be run (e.g. `enrich_limit` 30 ≈ $0.12) | Anthropic console, GitHub → Settings → Secrets |
| 👤 | Oracle Cloud account (card for verification only) and an Ampere VM, 1 OCPU / 4 GB, Ubuntu 24.04 | [DEPLOYMENT.md#oracle-cloud](DEPLOYMENT.md#oracle-cloud) steps 1–2 |
| 👤 | Oracle Security List ingress: TCP 80, TCP 443 (UDP 443 optional) | step 3 |
| 👤 | DuckDNS subdomain pointing at the VM's public IP | step 4 |
| 👤 | Make the GHCR packages `gjurme-api` and `gjurme-web` public (no token needed on the server) | step 6 |
| 👤 | Decide: stay free-only (a VM stopped as idle gets restarted by hand) or convert to Pay-As-You-Go with a $1 budget alert | step 8 |

The rows below apply to both paths. Skip the VPS/domain rows on the free path, and keep the Anthropic key off the server until you want to pay for AI analysis.

| | Action | Where | Notes |
|---|---|---|---|
| 👤 | **Anthropic API key** with a spend limit in the Anthropic console | `.env` on the server (`ANTHROPIC_API_KEY`); optionally a repository secret for the weekly live check | Without it the site runs, but nothing is classified. |
| 👤 | **VPS** (Ubuntu 24.04, 2 vCPU, 2–4 GB) | Any provider; ≈ $12–24/month, re-check prices | [DEPLOYMENT.md §1–2](DEPLOYMENT.md#step-by-step) |
| 👤 | **Domain + DNS** A/AAAA record to the server | Registrar | Caddy needs it before the first start to obtain the certificate. |
| 👤 | `ACME_EMAIL`, generated `POSTGRES_PASSWORD` and `ADMIN_API_TOKEN` | `/opt/gjurme/.env` (chmod 600) | `openssl rand -base64 36` |
| 👤 | GHCR pull access on the server (`docker login ghcr.io`), or make the two packages public | Server / GitHub Packages | [DEPLOYMENT.md §4](DEPLOYMENT.md#4-registry-access--owner) |
| 👤 | GitHub `production` environment with `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`; variables `DEPLOY_ENABLED=true`, `DOMAIN`, `PUBLIC_URL` | GitHub → Settings | [DEPLOYMENT.md §7](DEPLOYMENT.md#7-continuous-deployment--owner) |
| 👤 | Alert webhook (Slack/Discord/ntfy) | `.env` (`ALERT_WEBHOOK_URL`, `ALERT_WEBHOOK_FORMAT`) | Test with `gjurme alert-test`. |
| 👤 | Off-site backup bucket (recommended) | rclone config + `RCLONE_REMOTE` | [DEPLOYMENT.md §9](DEPLOYMENT.md#9-off-site-backups-optional-recommended--owner) |
| 👤 | **Private contact for correction/removal requests** on the About page | Repository variable `CONTACT_URL` (e.g. `mailto:press@your-domain`), used at image build | The default is the repository's GitHub issues, which are public. A person asking for their name to be removed should not have to post it publicly. Also set the server's `CONTACT_URL` (User-Agent and OpenAPI contact). |
| 👤 | Decide the default branch strategy | GitHub | Images and deploys follow the **default branch** (currently the development branch). Create `main` and make it the default if you prefer; nothing else changes. |
| 👤 | Optional legal review of the content-usage design | — | The design is conservative (metadata only, link-back, takedown), but no legal claims are made ([ADR-003](DECISIONS.md#adr-003-store-metadata-and-derived-data-only)). |

## 3. Launch-day steps ⬜

1. ⬜ **Model quality spot-check.** Run the *Source validation* workflow with the `ANTHROPIC_API_KEY` secret set and `enrich_limit` 30–50. Its review report lists every result next to its headline, with names dropped by grounding, tokens and cost per article, to compare with the ≈ $0.004 estimate. On a server with a key the equivalent is `gjurme enrich --limit 50` plus `admin quality` / `admin costs`. Optionally repeat with `LLM_MODEL=claude-haiku-4-5` before deciding the default.
2. ⬜ First deploy: `./deploy.sh <sha>` ([DEPLOYMENT.md §6](DEPLOYMENT.md#6-first-deploy)).
3. ⬜ Verify: `/health/ready`, `/api/v1/status` = `ok` after the first run, HSTS and CSP headers, `/metrics` = 404, admin endpoint without a token = 401, and the firewall (`ufw status`, or on Oracle `sudo iptables -L INPUT -n --line-numbers` showing 80/443 before the REJECT). In free mode, confirm the rule-based banner is shown.
4. ⬜ Run a backup and a restore test by hand once ([OPERATIONS.md](OPERATIONS.md#backups)).
5. ⬜ Set `PUBLIC_URL` and run the *Uptime monitor* workflow manually once.
6. ⬜ Set `DEPLOY_ENABLED=true` and confirm that the next push deploys through CI.
7. ⬜ Set the repository variables `PUBLIC_URL` and `CONTACT_URL` **before** the first CI image build. CI passes them into the web build (`VITE_PUBLIC_URL`, `VITE_CONTACT_URL`), which makes canonical links, Open Graph and the sitemap point at the real domain and shows the private contact.

## 4. First week ⬜

- ⬜ Daily glance ([OPERATIONS.md](OPERATIONS.md#daily-glance-2-minutes)): runs, costs, quality, alerts.
- ⬜ Watch the backlog and the budget: raise or lower `LLM_DAILY_BUDGET_USD` to match real volume.
- ⬜ First Sunday: confirm the automatic restore verification passed (`dc logs backup`).
- ⬜ Validate Albanian and North Macedonian candidates (A2, Euronews Albania, BalkanWeb, Reporter.al, Portalb) for geographic balance ([SOURCES.md](SOURCES.md)).

## 5. Known limitations at launch

- Coverage is Kosovo-heavy (all 5 verified sources).
- "Unique stories" only merges near-verbatim copies; paraphrased coverage of the same event counts separately (ADR-008).
- Tone and entities are machine-generated from headline and excerpt only, and can be wrong; the methodology page says so.
- One server: the recovery point is the last nightly backup.

## 6. Backlog (V2 candidates)

Message Batches API for backfills (−50% cost) · story clustering with embeddings · entity alias resolution · entity graph view · email or RSS alerts for followed entities · Serbian and Macedonian sources · public dataset export · daily rollup table if analytics latency matters at larger scale.
