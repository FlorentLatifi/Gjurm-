# Security

GJURMË is a public, read-only analytics site with one operator. There are no user accounts, no personal data collected from visitors, and no payments. The assets worth protecting are:

1. the **server and database**: integrity of the data, and availability;
2. the **secrets**: Anthropic API key (money), admin token (takedowns, kill switch), database password, deploy key;
3. the **LLM budget**, which must not be drainable by anyone outside;
4. the **publishers' trust**: polite fetching, no republication, working takedowns.

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| Traffic interception | HTTPS only (Caddy, automatic certificates), HTTP → HTTPS 308, HSTS 1 year | `frontend/Caddyfile` |
| XSS via article titles, LLM output or entity names | React renders text only. `dangerouslySetInnerHTML` is banned by an ESLint rule (CI fails), links go through `safeHref` (http/https only), and a strict CSP without inline scripts (`script-src 'self'`; the theme bootstrap is an external file). | `frontend/eslint.config.js`, `src/lib/format.ts`, Caddyfile |
| Clickjacking, MIME sniffing, referrer leaks | `frame-ancestors 'none'` / `X-Frame-Options: DENY`, `nosniff`, `strict-origin-when-cross-origin`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`; the API sends `default-src 'none'` | Caddyfile, `api/security.py` |
| SQL injection | All values are bound parameters. The few composed fragments (sort order, group-by column, optional joins) come from fixed dictionaries or constants, never from input. Ruff's bandit rules (`S608`) are on, and each exception is justified in place. | `analytics/queries.py` |
| Invalid input / resource exhaustion via queries | Pydantic-validated params: dates ≤ 366 days, page size ≤ 100, offsets bounded, search 2–120 chars, slugs by regex; 15 s statement timeout on every DB connection | `api/deps.py`, `api/routers/public.py`, `db/session.py` |
| Scraping / abuse / DoS of the API | Per-IP token buckets (300/min default, 90/min for search and admin), in-process response cache (2 min), bounded pool sizes and container memory limits. No WAF: a CDN such as Cloudflare in front is an option if needed. | `api/security.py`, compose |
| Admin endpoint abuse | Bearer token of at least 32 chars (enforced at startup in staging/production), compared with `hmac.compare_digest`; separate rate-limit bucket; every admin action logged with the reason | `api/security.py`, `config.py` |
| Operational data leaks | `/metrics` → 404 through Caddy; direct access needs the admin token when the request is public or carries `X-Forwarded-For`. Error responses never include stack traces or SQL. The publisher excerpt is never returned by the public API (tested). | `api/routers/ops.py`, tests |
| SSRF via feeds (a feed or redirect pointing at internal hosts) | Only `http`/`https`; each redirect hop is re-validated, and its host must resolve to a public address (no private, loopback, link-local or metadata ranges); max 5 redirects; 5 MB response cap; 15 s timeout | `ingestion/fetcher.py`, `ingestion/normalize.py` |
| Malicious XML | feedparser on Python ≥ 3.7.1, where the SAX parser does not resolve external entities by default; size cap before parsing | `ingestion/feed_parser.py` |
| Prompt injection through article text | The article is wrapped in tags with `<>&` escaped. The system prompt marks it as untrusted data. The output is constrained by a JSON schema, validated, and entities must be grounded in the text. The LLM has no tools and no side effects, so the worst case is a wrong label on one article. | `enrichment/` |
| LLM budget drain | No public endpoint triggers LLM calls: enrichment runs only in the scheduler, on newly ingested articles, under a daily hard cap; the kill switch is admin-only | `enrichment/budget.py` |
| Secret leakage | Secrets only via environment (`.env`, chmod 600, never committed), typed as `SecretStr` (never logged or serialized). **gitleaks** scans the full history on every push. GitHub secrets are scoped to the `production` environment. | CI `security` job |
| Vulnerable dependencies | Lockfiles (`uv.lock`, `package-lock.json`) installed frozen; `pip-audit` and `npm audit` in CI; **Trivy** fails the image build on fixable HIGH/CRITICAL, which it did on the official Caddy image, so Caddy is now built from source with patched Go and dependencies ([ADR-017](DECISIONS.md#adr-017-build-caddy-from-source-when-upstream-lags-on-fixes)); Dependabot weekly | `.github/workflows/ci.yml`, `.github/dependabot.yml` |
| Container escape / lateral movement | Both images run as a non-root user (UID 10001); Caddy holds only `CAP_NET_BIND_SERVICE` (verified: `CapEff 0x400`, `NoNewPrivs 1`). Read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, tmpfs `/tmp`, memory limits. The database is on an internal network with no route out; the API has no internet egress; only Caddy publishes ports. | Dockerfiles, `deploy/docker-compose.prod.yml` |
| Server compromise via SSH | Key-only SSH, root login without password disabled, fail2ban, ufw (22/80/443 only), unattended security upgrades | `deploy/scripts/bootstrap-server.sh` |
| Unsafe production configuration | The app refuses to start in staging/production with a short admin token, a `*` CORS origin, the fake LLM provider or the default database password; demo seeding refuses to run there | `config.py`, `demo.py` |
| Supply chain of the deploy | Images are built only by CI, tagged by commit SHA, scanned before push; the server never builds. The bootstrap script is fetched pinned to a commit and read before running. | CI, `DEPLOYMENT.md` |

## Privacy

- No cookies, no analytics or tracking scripts, no third-party requests from the browser: system fonts, all assets served from the same origin, and the CSP (`default-src 'self'`) enforces it.
- The theme preference is stored in `localStorage` on the visitor's device only.
- Rate-limit state is kept in memory and not persisted. The API writes no access log. Caddy's access log truncates visitor IPs (IPv4 /16, IPv6 /32) and drops `X-Forwarded-For` before writing, so the About page's "no full IP addresses" statement holds (verified in the running stack). Docker rotates logs at 5 × 10 MB per container.
- Stored content is publisher metadata plus derived analysis. Excerpts (LLM input) are purged after 90 days and never published ([DATA_MODEL.md](DATA_MODEL.md#retention)).
- People appear only as named entities from public news headlines. Takedown path: [OPERATIONS.md](OPERATIONS.md#takedown-request). The About page's contact defaults to public GitHub issues; set the `CONTACT_URL` repository variable (e.g. `mailto:`) so removal requests can be made privately.

## Accepted risks

| Risk | Why accepted | Mitigation / trigger to revisit |
|---|---|---|
| The `deploy` user is in the `docker` group, which is root-equivalent on the host | Single-purpose server; CI needs to run compose. The alternatives (rootless Docker, a forced-command wrapper) add complexity disproportionate to the asset. | Key-only SSH, a dedicated key stored as an environment secret, optional required reviewers on the `production` environment. Revisit if the server hosts anything else. |
| GitHub Actions are pinned to major-version tags, not commit SHAs | Readability and Dependabot updates; all actions are first-party or widely used (actions/*, docker/*, astral-sh, aquasecurity). | Pin to SHAs if the repository becomes a higher-value target. |
| One shared admin token, no per-user accounts | One operator. | Rotate on any suspicion ([OPERATIONS.md](OPERATIONS.md#rotate-secrets)); add OIDC/SSO if a team operates it. |
| No WAF or DDoS protection beyond rate limiting | Low-value target; cached, read-only responses. | Put a CDN in front (DNS change only). |
| OpenAPI docs are public (`EXPOSE_DOCS=true`) | The API is public by design; the docs help reuse. | `EXPOSE_DOCS=false` hides them. |
| Actions logs of the weekly live source check are public in a public repository | They contain only public headlines and statistics. | — |

## Verification (what was actually checked)

- CI on GitHub: gitleaks (full history), pip-audit, npm audit, ruff with bandit rules, mypy strict all pass. Trivy runs when images are built.
- Tests assert the security headers and CSP, admin auth (missing, wrong and right token), rate limiting (429 with `Retry-After`), `/metrics` protection, that the excerpt never appears in public responses, SSRF blocking (private IPs, redirect to a private host), and the production configuration guards.
- Local production rehearsal: HTTPS with HSTS and CSP present, `/metrics` → 404 through Caddy, and the app refusing to start with a short admin token.
- Not done: an external penetration test or a third-party review.

## Reporting a vulnerability

Please open a private security advisory on the GitHub repository (Security → Report a vulnerability) rather than a public issue.

## Pre-launch security checklist

- [ ] `.env` on the server is `chmod 600`, owned by `deploy`, and contains freshly generated secrets.
- [ ] `ADMIN_API_TOKEN` ≥ 32 random characters, stored in a password manager.
- [ ] Anthropic key has a spend limit in the Anthropic console, as a second cap next to `LLM_DAILY_BUDGET_USD`.
- [ ] GitHub `production` environment holds the deploy secrets (not repository-wide), optionally with required reviewers.
- [ ] `curl -sI https://$DOMAIN` shows HSTS and CSP; `/metrics` returns 404; `/api/v1/admin/runs` without a token returns 401.
- [ ] `ufw status` shows only 22/80/443; `ssh root@server` with a password fails.
- [ ] Off-site backup configured, or the risk of single-host backups consciously accepted.
