# Nisja e GJURMË-s: udhëzues në shqip

Ky udhëzues e çon projektin nga "kodi gati" te "faqja online". Ka dy pjesë:

- **Pjesa A: testi i cilësisë së Claude** (rreth 20 minuta, rreth $0.20). Tregon sa mirë i analizon Claude lajmet reale para se të paguash për to çdo ditë.
- **Pjesa B: faqja online falas** në Oracle Cloud Always Free me një subdomain falas nga DuckDNS (1–2 orë, kryesisht pritje).

Hapat me 👤 i bën pronari i projektit, sepse kërkojnë llogari, kartë ose vendim. Detajet teknike në anglisht janë te [DEPLOYMENT.md](DEPLOYMENT.md#oracle-cloud) dhe [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md).

> **Rregull i artë:** çelësat (`sk-ant-...`), fjalëkalimet dhe `.env` nuk futen **kurrë** në git, në chat apo në screenshot. Vendosen vetëm te GitHub Secrets ose te skedari `.env` në server.

---

## Pjesa A: testi i cilësisë së Claude

### A1. Çelësi API 👤

1. Hyr te **console.anthropic.com** dhe kontrollo te **Billing** që krediti (bonusi) është aty. Krediti "extra usage" i abonimit Claude.ai **nuk** vlen këtu. Duhet kredit API.
2. Te faqja e kufijve të shpenzimit (**Limits**) vendos një kufi mujor, p.sh. **$10**. Kjo është mbrojtje e dytë, përveç kufirit ditor të aplikacionit.
3. **API Keys → Create Key**, me emër `gjurme`. Kopjoje menjëherë, sepse shfaqet vetëm një herë.

### A2. Çelësi te GitHub 👤

GitHub → repo **Gjurm-** → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Secret |
|---|---|
| `ANTHROPIC_API_KEY` | çelësi `sk-ant-...` |

### A3. Nise testin 👤

GitHub → **Actions → Source validation → Run workflow**:

| Fusha | Vlera |
|---|---|
| Branch | `claude/gallant-franklin-2uhex2` (dega kryesore) |
| `enrich_limit` | `30` (kosto rreth $0.10–0.20, kufi i fortë $0.60) |
| `export_headlines` | `0` |

Pas 2–3 minutash hape run-in dhe shiko te **Summary** seksionin **Claude quality review**:

- tabela e parë tregon koston totale dhe për artikull (vlerësimi është rreth $0.004 për artikull);
- tabela e fundit tregon për çdo lajm temën, tonin, emrat dhe përmbledhjen. Kontrollo nëse kanë kuptim.

**Opsionale:** përsërite testin me modelin më të lirë. Ndrysho `LLM_MODEL` te hapi *Enrich (Claude, capped)* në `.github/workflows/sources.yml`, ose kërko që ta bëjmë në një sesion.

Dërgoja rezultatin sesionit të zhvillimit (link ose copy-paste i Summary). Prej tij vendosim modelin (Sonnet 5 apo Haiku 4.5) dhe kufirin ditor.

---

## Pjesa B: faqja online falas

### B1. Llogaria Oracle 👤

**oracle.com/cloud/free → Sign up**. Duhen numri i telefonit dhe një **kartë krediti ose debiti vetëm për verifikim** (një autorizim i përkohshëm $1). Kartat prepaid dhe virtuale refuzohen.

**Home region: Frankfurt** (ose një tjetër në Evropë). Nuk ndryshohet më vonë, dhe VM-të falas krijohen vetëm aty.

### B2. Çelësi SSH në kompjuterin tënd 👤

Në terminal (në Windows: PowerShell):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/gjurme_oracle -N ""
cat ~/.ssh/gjurme_oracle.pub        # këtë e ngjit te Oracle në hapin B3
```

### B3. Serveri (VM) 👤

**Compute → Instances → Create instance**:

| Fusha | Vlera |
|---|---|
| Image | **Canonical Ubuntu 24.04** |
| Shape | **VM.Standard.A1.Flex** (Ampere), **1 OCPU, 4 GB** |
| Networking | VCN e re me *public subnet*, **Assign public IPv4 address: Po** |
| SSH keys | ngjit `gjurme_oracle.pub` |

Nëse del **"Out of capacity"**, provo më vonë ose zgjidh një *availability domain* tjetër. Ndodh shpesh te pjesa falas.

Shëno **IP-në publike** të VM-së.

### B4. Hap portat 80 dhe 443 👤

**Networking → Virtual cloud networks → VCN-ja jote → Security Lists → Default → Add Ingress Rules**, me source `0.0.0.0/0`:

- TCP, destination port **80**
- TCP, destination port **443**

### B5. Subdomain falas 👤

**duckdns.org** → hyr (p.sh. me GitHub) → krijo subdomain-in, p.sh. `gjurme` → te **current ip** vendos IP-në e VM-së → **update ip**.

Adresa jote bëhet `gjurme.duckdns.org`. Nëse është e zënë, zgjidh një emër tjetër dhe përdore kudo më poshtë.

### B6. Përgatit serverin (një herë)

```bash
ssh -i ~/.ssh/gjurme_oracle ubuntu@<IP>
sudo -i
curl -fsSLO https://raw.githubusercontent.com/FlorentLatifi/Gjurm-/<commit-sha>/deploy/scripts/bootstrap-server.sh
less bootstrap-server.sh      # lexoje para se ta nisësh (q për të dalë)
bash bootstrap-server.sh
```

`<commit-sha>` është commit-i që do të publikosh: hash-i i plotë i commit-it të fundit me CI të gjelbër në degën kryesore (GitHub → Actions → CI). Skripti instalon Docker, krijon përdoruesin `deploy` dhe dosjen `/opt/gjurme`, dhe në Oracle hap portat 80/443 pa aktivizuar UFW.

Pastaj jepi përdoruesit `deploy` të njëjtin çelës SSH:

```bash
mkdir -p /home/deploy/.ssh
cp /home/ubuntu/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys
exit; exit
```

### B7. Bëji imazhet publike 👤

GitHub → profili yt → **Packages** → `gjurme-api` → **Package settings → Change visibility → Public**. Bëj të njëjtën gjë për `gjurme-web`. Kështu serveri i shkarkon pa token.

### B8. Konfigurimi (`.env`)

Nga kompjuteri yt, në dosjen e repos, në të njëjtin commit si në B6 (`git checkout <commit-sha>`):

```bash
scp -i ~/.ssh/gjurme_oracle deploy/docker-compose.prod.yml deploy/scripts/deploy.sh deploy/.env.example deploy@<IP>:/opt/gjurme/
scp -i ~/.ssh/gjurme_oracle -r deploy/backup deploy@<IP>:/opt/gjurme/
ssh -i ~/.ssh/gjurme_oracle deploy@<IP>
cd /opt/gjurme
cp .env.example .env && chmod 600 .env
openssl rand -base64 36     # → POSTGRES_PASSWORD
openssl rand -base64 36     # → ADMIN_API_TOKEN (ruaje diku të sigurt, të duhet për faqet admin)
nano .env
```

Ndrysho te `.env`:

| Variabla | Vlera |
|---|---|
| `DOMAIN` | `gjurme.duckdns.org` |
| `ACME_EMAIL` | email-i yt (për certifikatën HTTPS) |
| `POSTGRES_PASSWORD` | vlera e parë e gjeneruar |
| `ADMIN_API_TOKEN` | vlera e dytë e gjeneruar |

**Mënyra e analizës.** Zgjidh njërën:

- **Falas (rregulla me fjalë kyçe):** lëri siç janë `LLM_PROVIDER=fake` dhe `ALLOW_FAKE_LLM_IN_PRODUCTION=true`. Faqja shfaq një banner që e thotë këtë hapur.
- **Me Claude (me kreditin API):** fshi ose komento dy rreshtat e mësipërm dhe vendos:

  ```env
  LLM_PROVIDER=anthropic
  ANTHROPIC_API_KEY=sk-ant-...
  LLM_MODEL=claude-haiku-4-5          # ose claude-sonnet-5, sipas testit të Pjesës A
  LLM_DAILY_BUDGET_USD=1.00           # kufi i fortë ditor; me $100 kredit zgjat ~100 ditë
  ```

Ruaje me `Ctrl+O`, `Enter`, dhe dil me `Ctrl+X`.

### B9. Publikimi i parë

Ende brenda serverit, në `/opt/gjurme`:

```bash
./deploy.sh <commit-sha>
```

Skripti shkarkon imazhet, nis databazën, bën migrimet dhe pret deri në 120 sekonda që faqja të përgjigjet. Nëse diçka dështon, kthehet vetë te versioni i mëparshëm.

### B10. Kontrollo

Hap në shfletues `https://gjurme.duckdns.org`. Faqja e parë mund të duket bosh deri sa të përfundojë run-i i parë (rreth 15 minuta).

```bash
curl -fsS https://gjurme.duckdns.org/health/ready
curl -fsS https://gjurme.duckdns.org/api/v1/status
alias dc='IMAGE_TAG=$(cat .deploy-state/current) docker compose -f docker-compose.prod.yml'
dc ps                  # të gjitha "running" / "healthy"
```

Skedari i Docker Compose kërkon `IMAGE_TAG`, prandaj përdore gjithmonë aliasin `dc` (ose shiko [OPERATIONS.md](OPERATIONS.md)). Pa të, komandat `docker compose` japin gabimin `IMAGE_TAG must be set`.

Nëse certifikata HTTPS vonon, shiko `dc logs web`. Zakonisht DuckDNS vonohet pak dhe Caddy provon përsëri vetë.

### B11. Pas publikimit 👤

1. GitHub → **Settings → Secrets and variables → Actions → Variables**:
   - `PUBLIC_URL` = `https://gjurme.duckdns.org`
   - `CONTACT_URL` = `mailto:email-yt@...` (kontakti privat për korrigjime/heqje nga faqja About)
2. **Actions → Uptime monitor → Run workflow** një herë. Pas kësaj të njofton me email nëse faqja bie.
3. Oracle mund ta **ndalë** një VM falas që punon shumë pak për 7 ditë. Nëse të vjen email-i i monitorit, niseni përsëri nga konsola (të dhënat ruhen). Për ta shmangur: **Billing → Upgrade to Pay-As-You-Go** dhe **Budgets → alert $1**. Burimet falas mbeten falas.

Publikimi automatik nga GitHub në çdo push (CI → server) është opsional. Hapat janë te [DEPLOYMENT.md §3 dhe §7](DEPLOYMENT.md#3-deploy-key-for-ci--owner).

---

## Kur ta kalosh nga falas te Claude

Në server, te `/opt/gjurme`:

```bash
nano .env                                   # vendos 4 rreshtat e mënyrës "Me Claude" nga hapi B8
./deploy.sh "$(cat .deploy-state/current)"  # rinis kontejnerët me .env-in e ri (me kontroll shëndeti)
IMAGE_TAG=$(cat .deploy-state/current) docker compose -f docker-compose.prod.yml \
  exec scheduler gjurme enrich-requeue --provider fake
```

Komanda e fundit i ri-analizon me Claude lajmet që i kishin analizuar rregullat, brenda kufirit ditor. Banneri "rule-based" zhduket vetë.

---

## AI falas (pa Claude)

Aplikacioni mund të përdorë edhe modele AI falas, përmes `LLM_PROVIDER=openai_compatible`. Detajet teknike janë te [AI_ENRICHMENT.md](AI_ENRICHMENT.md#free-models).

### 1. Mat cilësinë para se ta përdorësh (falas, pa server)

GitHub → **Actions → Free model quality → Run workflow**:

| Fusha | Vlera |
|---|---|
| `model` | `gemma3:4b` (provo edhe `qwen3:4b`) |
| `enrich_limit` | `15` |

Pas 10–20 minutash, te **Summary** e sheh për çdo lajm temën, tonin, emrat dhe përmbledhjen, si dhe sa sekonda iu desh modelit për një lajm. Krahasoje me raportin e Claude-it (Pjesa A) dhe me rregullat.

### 2. Modeli lokal në serverin Oracle

Modeli kërkon më shumë memorie se sa aplikacioni vetë. Në hapin B3 zgjidh **2 OCPU dhe 12 GB** (i gjithë limiti falas). Nëse VM-ja është krijuar me 4 GB, ndryshoja madhësinë te Oracle: *Instance → Edit → Shape*.

Në server, te `/opt/gjurme`:

```bash
nano .env        # shto: COMPOSE_PROFILES=local-llm   (LLM_PROVIDER mbetet fake për momentin)
./deploy.sh "$(cat .deploy-state/current)"
alias dc='IMAGE_TAG=$(cat .deploy-state/current) docker compose -f docker-compose.prod.yml'
dc exec ollama ollama pull gemma3:4b         # shkarkimi zgjat disa minuta
```

Pastaj te `.env` hiq ose komento `LLM_PROVIDER=fake` dhe `ALLOW_FAKE_LLM_IN_PRODUCTION=true`, dhe shto:

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=gemma3:4b
LLM_TIMEOUT_SECONDS=600
ENRICH_CONCURRENCY=1
```

```bash
./deploy.sh "$(cat .deploy-state/current)"
dc exec scheduler gjurme enrich-requeue --provider fake    # ri-analizo me modelin lajmet e rregullave
```

### 3. Kalimi te Claude më vonë

Ndrysho vetëm `.env` (`LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `LLM_MODEL`, `LLM_DAILY_BUDGET_USD`), rinise me `./deploy.sh`, dhe ri-analizo me `dc exec scheduler gjurme enrich-requeue --provider openai_compatible`. Kontejnerin e modelit lokal e ndal duke hequr `COMPOSE_PROFILES=local-llm` dhe me `dc stop ollama`.

**Kujdes:** krahasimet mes portaleve janë të drejta vetëm kur të gjitha lajmet janë analizuar me të njëjtin model. Prandaj, pas çdo ndërrimi, ri-analizo edhe lajmet e vjetra.
