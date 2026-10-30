# Nisja e GJURMË-s: udhëzues në shqip

Ky udhëzues e çon projektin nga "kodi gati" te "faqja online". Ka tri pjesë:

- **Pjesa A: testi i cilësisë së Claude** (rreth 20 minuta, rreth $0.20). Tregon sa mirë i analizon Claude lajmet reale para se të paguash për to çdo ditë. Është opsionale.
- **Pjesa B: faqja online falas, pa server** (rreth 30 minuta, pa kartë bankare): Vercel + Neon + GitHub. **E rekomanduar.**
- **Pjesa C: server falas në Oracle Cloud**, me një subdomain falas nga DuckDNS (1–2 orë). Kërkon kartë për verifikim, por jep më shumë hapësirë. Alternativë për kur Pjesa B nuk mjafton.

Hapat me 👤 i bën pronari i projektit, sepse kërkojnë llogari ose vendim. Detajet teknike në anglisht janë te [DEPLOYMENT.md](DEPLOYMENT.md) dhe [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md).

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
| Branch | `florent/gallant-franklin-2uhex2` (dega kryesore) |
| `enrich_limit` | `30` (kosto rreth $0.10–0.20, kufi i fortë $0.60) |
| `export_headlines` | `0` |

Pas 2–3 minutash hape run-in dhe shiko te **Summary** seksionin **Claude quality review**:

- tabela e parë tregon koston totale dhe për artikull (vlerësimi është rreth $0.004 për artikull);
- tabela e fundit tregon për çdo lajm temën, tonin, emrat dhe përmbledhjen. Kontrollo nëse kanë kuptim.

**Opsionale:** përsërite testin me modelin më të lirë. Ndrysho `LLM_MODEL` te hapi *Enrich (Claude, capped)* në `.github/workflows/sources.yml`, ose kërko që ta bëjmë në një sesion.

Dërgoja rezultatin sesionit të zhvillimit (link ose copy-paste i Summary). Prej tij vendosim modelin (Sonnet 5 apo Haiku 4.5) dhe kufirin ditor.

---

## Pjesa B: faqja online falas, pa server (e rekomanduar)

Kjo rrugë nuk kërkon kartë bankare, server apo domain. Përdor tri shërbime falas. Në të tria hyn me llogarinë tënde të GitHub-it:

- **Neon**: databaza (PostgreSQL), 1 GB falas.
- **Vercel**: faqja dhe API-ja, me HTTPS, në adresën `https://<emri>.vercel.app`.
- **GitHub Actions**: çdo 30 minuta merr lajmet, i analizon dhe i grupon në histori. Një herë në javë ruan një kopje rezervë.

Duhen rreth 30 minuta. Detajet teknike në anglisht janë te [DEPLOYMENT.md](DEPLOYMENT.md#free-hosting-without-a-server) dhe vendimi te [ADR-027](DECISIONS.md#adr-027-a-0-path-without-a-server-vercel--neon--github-actions).

### B1. Databaza te Neon 👤

1. Hap **neon.com** → **Sign up** → **Continue with GitHub**. Nuk kërkohet kartë.
2. Krijo projektin:

   | Fusha | Vlera |
   |---|---|
   | Project name | `gjurme` |
   | Postgres version | lëre siç është |
   | Region | **AWS US East 1 (N. Virginia)** |

   Pse në SHBA: aty punojnë edhe run-et e GitHub-it dhe funksioni i Vercel-it, prandaj databaza u përgjigjet shpejt. Lexuesit në Kosovë dhe Shqipëri e marrin faqen nga serverat e Vercel-it më afër tyre, në Evropë.
3. Te paneli i projektit kliko **Connect**. **Fike "Connection pooling"**: duhet lidhja e drejtpërdrejtë, ajo ku adresa **nuk** ka `-pooler`. Kopjo vargun që fillon me `postgresql://`. Ky është `DATABASE_URL`-ja jote.

> Ruaje `DATABASE_URL`-në si fjalëkalim: kushdo që e ka, e ka databazën. Vendose vetëm te GitHub Secrets dhe te Vercel, kurrë në git apo në chat.

### B2. Sekretet te GitHub 👤

GitHub → repo **Gjurm-** → **Settings → Secrets and variables → Actions**.

Te skeda **Secrets → New repository secret**:

| Name | Secret |
|---|---|
| `DATABASE_URL` | vargu nga B1 |
| `BACKUP_PASSPHRASE` | një frazë e gjatë e rastësishme, p.sh. 6–8 fjalë. **Ruaje diku të sigurt** (p.sh. në një menaxher fjalëkalimesh): pa të, kopjet rezervë nuk hapen dot. |

Te skeda **Variables → New repository variable**:

| Name | Value |
|---|---|
| `FREE_HOSTING` | `true` |

### B3. Mbushja e parë e databazës 👤

GitHub → **Actions → Free hosting → Run workflow** (task: `pipeline`) → **Run workflow**.

Pas rreth 10 minutash run-i duhet të dalë i gjelbër ✅. Ai krijon tabelat, merr lajmet e para nga 19 mediat dhe i analizon. Run-et e ardhshme zgjasin 1–4 minuta, sepse marrin vetëm lajmet e reja. Që të përsëriten saktë çdo 30 minuta, vendos edhe orën e jashtme te hapi B9.

Nëse del i kuq ❌, hape dhe shiko hapin e kuq:

- *"Add the DATABASE_URL secret"*: kthehu te B2.
- gabim lidhjeje (*connection*, *password*): kontrollo që vargu është i plotë dhe që adresa nuk ka `-pooler`.

### B4. Faqja te Vercel 👤

1. Hap **vercel.com/signup** → zgjidh planin **Hobby** → **Continue with GitHub**. Nuk kërkohet kartë.
2. **Add New… → Project** → te lista zgjidh **Gjurm-** → **Import**. Nëse repo nuk duket, kliko **Adjust GitHub App Permissions** dhe jepi Vercel-it qasje te ky repo.
3. Në faqen e konfigurimit:

   | Fusha | Vlera |
   |---|---|
   | Project Name | `gjurme`: adresa bëhet `https://gjurme.vercel.app`. Nëse është e zënë, zgjidh një emër tjetër dhe përdore kudo më poshtë. |
   | Framework Preset | lëre **Other**: gjithçka tjetër vjen nga `vercel.json` |
   | Root Directory | lëre `./` |
   | Environment Variables | Key `DATABASE_URL`, Value: i njëjti varg si te B1 |

4. **Deploy**. Pas 2–3 minutash del *Congratulations!* → **Continue to Dashboard** → **Visit**.

Prej tani Vercel e boton faqen vetë sa herë që ndryshon dega kryesore (`florent/gallant-franklin-2uhex2`). Për çdo PR krijon edhe një faqe provë (*preview*).

### B5. Kontrollo 👤

- `https://gjurme.vercel.app`: faqja. Historitë dalin kur disa media kanë raportuar të njëjtën ngjarje, prandaj në fillim mund të duhen disa run-e.
- `https://gjurme.vercel.app/health/ready`: duhet të tregojë `"database": true`.
- `https://gjurme.vercel.app/api/v1/status`: pas run-it të parë, `"status": "ok"`.
- Ndaje lidhjen e një historie në WhatsApp ose Telegram. Pamja paraprake duhet të tregojë titullin e historisë, jo faqen kryesore.

### B6. Pas publikimit 👤

1. **Monitori i jashtëm.** GitHub → Variables: `PUBLIC_URL` = `https://gjurme.vercel.app`. Kjo ndez **Actions → Uptime monitor**, që të njofton me email nëse faqja bie ose lajmet nuk përditësohen.
2. **Njoftime në telefon** (opsionale, falas, pa llogari): instalo aplikacionin **ntfy** dhe abonohu te një temë me emër të rastësishëm, p.sh. `gjurme-7f3k9q`. Te GitHub shto secret-in `ALERT_WEBHOOK_URL` = `https://ntfy.sh/gjurme-7f3k9q` dhe variablën `ALERT_WEBHOOK_FORMAT` = `ntfy`. Të vjen njoftim kur një run dështon, kur bien mediat ose kur databaza mbushet.
3. **healthchecks.io** (opsionale, falas): krijo kontrollin *pipeline* (period 30 minuta, tolerancë 1 orë) dhe vendose URL-në e tij si secret `HEALTHCHECK_PING_URL`. Të njofton nëse run-et ndalen.
4. **Kontakti te faqja About** (opsionale): Vercel → projekti → **Settings → Environment Variables** → `VITE_CONTACT_URL` = `mailto:email-yt@...` → **Deployments → … → Redeploy**.
5. **Claude** (opsionale): shto secret-in `ANTHROPIC_API_KEY`. Run-et e ardhshme e përdorin vetë, me kufi ditor $2. Pastaj **Actions → Free hosting → Run workflow → task: `reanalyse`** i ri-analizon me Claude lajmet që i kishin analizuar rregullat. Banneri *rule-based* zhduket vetë.
6. **Domain i yti** (opsionale, rreth $10 në vit): Vercel → projekti → **Settings → Domains → Add**. Pas një **Redeploy**, faqja e merr adresën e re vetë. Ndrysho edhe `PUBLIC_URL` te GitHub.

### B7. Kufijtë falas

Shifrat e GJURMË-s janë vlerësime për fillimin. Kontrolloji herë pas here te paneli **Usage** i Neon-it dhe i Vercel-it.

| Shërbimi | Kufiri falas | GJURMË (vlerësim) | Çfarë ndodh në kufi |
|---|---|---|---|
| Neon: hapësira | 1 GB | rreth 250–400 MB në muaj në fillim, me 19 media; më ngadalë kur fillon fshirja e të dhënave të vjetra (të dhënat e papërpunuara të feed-eve pas 7 ditësh, përmbledhjet e feed-eve pas 30) | shkrimet ndalen |
| Neon: koha e punës | 100 orë-CU në muaj | rreth 45 nga run-et, plus vizitorët | databaza ndalet deri në muajin tjetër |
| Neon: transferimi | 5 GB në muaj | rreth 2–3 GB | njësoj |
| Vercel | 4 orë CPU, 1 milion thirrje, 100 GB trafik në muaj | përgjigjet ruhen 5 minuta në CDN, prandaj shumica e vizitave nuk e zgjojnë API-në | projekti pezullohet deri në muajin tjetër |
| GitHub Actions | pa kufi për repo publike | 48 run-e në ditë | — |

Kontrolli `database_size` të paralajmëron kur databaza arrin 80 % të 1 GB-it: si shënim i verdhë te faqja e run-it në GitHub, dhe në telefon nëse ke vendosur njoftimet (B6).

Kur afrohesh te kufijtë ke dy rrugë:

1. Neon → **Billing → Launch**: paguan vetëm sa përdor; për këtë madhësi zakonisht disa dollarë në muaj.
2. Ose kalon te një server (Pjesa C). Kopja rezervë e fundit ngarkohet atje me `pg_restore`.

**Vercel Hobby është vetëm për përdorim personal, jo-komercial:** pa reklama dhe pa pagesa. Nëse GJURMË fillon të fitojë para, kalo te Vercel Pro ($20 në muaj) ose te një server (Pjesa C).

### B8. Kopjet rezervë dhe rikthimi

Një herë në javë, workflow-i e ruan databazën të enkriptuar si *artifact*, që mbahet 35 ditë: **Actions → Free hosting** → run-i me kopjen → **Artifacts**. Kopja bëhet me run-in e parë pasi e fundit është më e vjetër se 7 ditë, kështu që nuk varet nga orari i GitHub-it. Kopje mund të bësh edhe vetë kur të duash: **Run workflow → task: `backup`**.

Rikthimi, në një kompjuter me `gpg` dhe klientin e PostgreSQL-it:

```bash
gpg -d gjurme-2026-11-01.dump.gpg > gjurme.dump        # kërkon BACKUP_PASSPHRASE
pg_restore --clean --if-exists --no-owner --dbname "postgresql://..." gjurme.dump
```

Neon ruan edhe historinë e 6 orëve të fundit (**Instant restore**), për gabimet e menjëhershme.

**Run-et automatike.** GitHub i ndal proceset e planifikuara të një repo publike pas 60 ditësh pa asnjë aktivitet. Workflow-i e rindez veten në çdo run, por nëse prapëseprapë ndalet: **Actions → Free hosting → Enable workflow**.

### B9. Ora e saktë: cron-job.org 👤 (e domosdoshme)

GitHub i nis run-et e planifikuara me vonesë kur është i ngarkuar. Në tetor 2026, run-et "çdo 30 minuta" u nisën çdo 2–5 orë. Kështu lajmet dilnin me orë vonesë, mediat me feed të shkurtër humbnin lajme dhe monitori dërgonte email-e "stale". Zgjidhja është një orë e jashtme falas, që e nis workflow-in me saktësi çdo 30 minuta.

**1. Çelësi te GitHub** (vetëm për të nisur run-et, jo për të ndryshuar kodin):

1. GitHub → foto e profilit → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. **Token name:** `gjurme-cron`. **Expiration:** 1 vit (shëno në kalendar ta ripërtërish).
3. **Repository access:** *Only select repositories* → **Gjurm-**.
4. **Permissions → Repository permissions → Actions: Read and write**. Asgjë tjetër.
5. **Generate token** dhe kopjoje (`github_pat_...`). Mos e ndaj në chat apo screenshot.

**2. Puna te cron-job.org** (falas, pa kartë):

1. **cron-job.org → Sign up**, konfirmo email-in → **Create cronjob**.
2. **Title:** `GJURMË pipeline`.
3. **URL:** `https://api.github.com/repos/FlorentLatifi/Gjurm-/actions/workflows/free-hosting.yml/dispatches`
4. **Execution schedule:** *Custom*, minutat `11` dhe `41`, çdo orë, çdo ditë. Ose *Every 30 minutes*.
5. Te skeda **Advanced**:
   - **Request method:** `POST`
   - **Headers**, tre rreshta:
     - `Accept` = `application/vnd.github+json`
     - `Authorization` = `Bearer github_pat_...` (çelësi nga hapi 1)
     - `X-GitHub-Api-Version` = `2022-11-28`
   - **Request body:** `{"ref":"florent/gallant-franklin-2uhex2","inputs":{"task":"pipeline"}}`
6. **Create**. Pastaj **Test run**: duhet të kthejë **204**. Te **Actions → Free hosting** del një run i ri me *workflow_dispatch*.

Kontroll pas një dite: **Actions → Free hosting** duhet të ketë një run çdo 30 minuta (secili 1–4 minuta), dhe **Actions → Uptime monitor** duhet të jetë i gjelbër. Kopja rezervë bëhet vetë me run-in e parë pas 7 ditësh.

Nëse cron-job.org kthen **401**, çelësi ka skaduar ose është kopjuar gabim: krijo një të ri (hapi 1) dhe ndrysho rreshtin `Authorization`. Nëse kthen **404**, kontrollo URL-në dhe që çelësi ka qasje te **Gjurm-**.

---

## Pjesa C: server falas në Oracle (alternativë)

### C1. Llogaria Oracle 👤

**oracle.com/cloud/free → Sign up**. Duhen numri i telefonit dhe një **kartë krediti ose debiti vetëm për verifikim** (një autorizim i përkohshëm $1). Kartat prepaid dhe virtuale refuzohen.

**Home region: Frankfurt** (ose një tjetër në Evropë). Nuk ndryshohet më vonë, dhe VM-të falas krijohen vetëm aty.

### C2. Çelësi SSH në kompjuterin tënd 👤

Në terminal (në Windows: PowerShell):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/gjurme_oracle -N ""
cat ~/.ssh/gjurme_oracle.pub        # këtë e ngjit te Oracle në hapin C3
```

### C3. Serveri (VM) 👤

**Compute → Instances → Create instance**:

| Fusha | Vlera |
|---|---|
| Image | **Canonical Ubuntu 24.04** |
| Shape | **VM.Standard.A1.Flex** (Ampere), **1 OCPU, 4 GB** |
| Networking | VCN e re me *public subnet*, **Assign public IPv4 address: Po** |
| SSH keys | ngjit `gjurme_oracle.pub` |

Nëse del **"Out of capacity"**, provo më vonë ose zgjidh një *availability domain* tjetër. Ndodh shpesh te pjesa falas.

Shëno **IP-në publike** të VM-së.

### C4. Hap portat 80 dhe 443 👤

**Networking → Virtual cloud networks → VCN-ja jote → Security Lists → Default → Add Ingress Rules**, me source `0.0.0.0/0`:

- TCP, destination port **80**
- TCP, destination port **443**

### C5. Subdomain falas 👤

**duckdns.org** → hyr (p.sh. me GitHub) → krijo subdomain-in, p.sh. `gjurme` → te **current ip** vendos IP-në e VM-së → **update ip**.

Adresa jote bëhet `gjurme.duckdns.org`. Nëse është e zënë, zgjidh një emër tjetër dhe përdore kudo më poshtë.

### C6. Përgatit serverin (një herë)

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

### C7. Bëji imazhet publike 👤

GitHub → profili yt → **Packages** → `gjurme-api` → **Package settings → Change visibility → Public**. Bëj të njëjtën gjë për `gjurme-web`. Kështu serveri i shkarkon pa token.

### C8. Konfigurimi (`.env`)

Nga kompjuteri yt, në dosjen e repos, në të njëjtin commit si në C6 (`git checkout <commit-sha>`):

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

### C9. Publikimi i parë

Ende brenda serverit, në `/opt/gjurme`:

```bash
./deploy.sh <commit-sha>
```

Skripti shkarkon imazhet, nis databazën, bën migrimet dhe pret deri në 120 sekonda që faqja të përgjigjet. Nëse diçka dështon, kthehet vetë te versioni i mëparshëm.

### C10. Kontrollo

Hap në shfletues `https://gjurme.duckdns.org`. Faqja e parë mund të duket bosh deri sa të përfundojë run-i i parë (rreth 15 minuta).

```bash
curl -fsS https://gjurme.duckdns.org/health/ready
curl -fsS https://gjurme.duckdns.org/api/v1/status
alias dc='IMAGE_TAG=$(cat .deploy-state/running) docker compose -f docker-compose.prod.yml'
dc ps                  # të gjitha "running" / "healthy"
```

Skedari i Docker Compose kërkon `IMAGE_TAG`, prandaj përdore gjithmonë aliasin `dc` (ose shiko [OPERATIONS.md](OPERATIONS.md)). Pa të, komandat `docker compose` japin gabimin `IMAGE_TAG must be set`.

Nëse certifikata HTTPS vonon, shiko `dc logs web`. Zakonisht DuckDNS vonohet pak dhe Caddy provon përsëri vetë.

**Kopjet rezervë.** Kontejneri i kopjeve rezervë punon si përdoruesi 70, prandaj dosja `backups` duhet t'i përkasë atij. Skripti i ri i instalimit e bën vetë. Nëse serveri është instaluar para tetorit 2026, `deploy.sh` shfaq një paralajmërim; rregulloje një herë:

```bash
sudo chown 70:70 /opt/gjurme/backups && sudo chmod 700 /opt/gjurme/backups && sudo chmod 755 /opt/gjurme/backup
dc run --rm backup sh /scripts/backup.sh   # duhet të përfundojë me "backup ok"
```

**Kontrolle "dead-man" (falas, të rekomanduara).** Te healthchecks.io krijo dy kontrolle: *pipeline* (çdo 15 min, tolerancë 1 orë) dhe *backup* (çdo ditë, tolerancë 2 orë). Vendosi URL-të e tyre te `.env` si `HEALTHCHECK_PING_URL` dhe `BACKUP_HEALTHCHECK_URL`, pastaj `./deploy.sh "$(cat .deploy-state/current)"`. Nëse run-et ose kopjet rezervë ndalen (edhe kur bie i gjithë serveri), shërbimi të njofton me e-mail.

Kontrollo edhe ndarjen e lajmeve: kopjo lidhjen e një historie (`https://gjurme.duckdns.org/stories/…`) në WhatsApp ose Telegram. Pamja paraprake duhet të tregojë titullin e historisë dhe "N outlets covered this story", jo faqen kryesore. Nëse tregon faqen kryesore, kontrollo që `DOMAIN` te `.env` është i saktë (lidhjet në pamje paraprake ndërtohen prej tij).

### C11. Pas publikimit 👤

1. GitHub → **Settings → Secrets and variables → Actions → Variables**:
   - `PUBLIC_URL` = `https://gjurme.duckdns.org`
   - `CONTACT_URL` = `mailto:email-yt@...` (kontakti privat për korrigjime/heqje nga faqja About)
2. **Actions → Uptime monitor → Run workflow** një herë. Pas kësaj të njofton me email nëse faqja bie.
3. Oracle mund ta **ndalë** një VM falas që punon shumë pak për 7 ditë. Nëse të vjen email-i i monitorit, niseni përsëri nga konsola (të dhënat ruhen). Për ta shmangur: **Billing → Upgrade to Pay-As-You-Go** dhe **Budgets → alert $1**. Burimet falas mbeten falas.

Publikimi automatik nga GitHub në çdo push (CI → server) është opsional. Hapat janë te [DEPLOYMENT.md §3 dhe §7](DEPLOYMENT.md#3-deploy-key-for-ci--owner).

---

## GJURMË si Ground News: historitë, Blindspot dhe vlerësimi i mediave

Faqja kryesore tani funksionon si [Ground News](https://ground.news/):

- **Historitë (Stories).** Artikujt e mediave të ndryshme për të njëjtën ngjarje bashkohen në një "histori". Për secilën shihet sa media e mbuluan, kush e raportoi i pari, si e titulloi secila media (krah për krah, me lidhje te origjinali) dhe një shirit që e ndan mbulimin sipas **anësisë** (majtas · qendër · djathtas · pa vlerësim), **rajonit** (Kosovë, Shqipëri, Maqedoni e Veriut), **pronësisë** dhe **faktualitetit**.
- **Blindspot.** Histori që i mbuloi kryesisht njëra anë, ose histori për një vend që mediat e atij vendi nuk i raportuan (p.sh. lajm për Shqipërinë që e dhanë vetëm mediat e Kosovës).
- **Profili i medias.** Vlerësimet dhe baza e tyre, pronësia, sa histori mbulon, sa herë raporton e para, "ekskluzivet".
- **My news bias.** Ekuilibri i mediave që lexon vetë përdoruesi. Ruhet vetëm në shfletuesin e tij, pa llogari e pa cookie.
- Paneli i vjetër i statistikave është te `/dashboard`.

### Vlerësimi i mediave 👤

Mediat reale janë **pa vlerësim** ("unrated") për anësinë dhe faktualitetin, sepse këto janë gjykime redaksionale dhe softueri nuk i shpik. Derisa t'i vlerësosh, faqja i ndan historitë sipas rajonit (që punon menjëherë) dhe shiriti i anësisë tregon "Unrated".

Për t'i vlerësuar, te `backend/src/gjurme/sources/sources.yaml`, për çdo media:

```yaml
    bias: center            # left | lean_left | center | lean_right | right | unrated
    factuality: high        # very_high | high | mixed | low | very_low | unrated
    ownership: private      # private | media_group | public | state | public_international | nonprofit | unknown
    owner: Emri i pronarit  # opsional, informacion publik
    ratings_note: "Vlerësim redaksional, nëntor 2026: … (mbi çka bazohet)"
```

Rregullat:

1. **Mos hamendëso.** Vendos `bias` ose `factuality` vetëm pas një shqyrtimi të dokumentuar (kush e bëri, kur, mbi çfarë prove: mostër artikujsh, politika e korrigjimeve, pronësia). Pa `ratings_note`, sistemi e refuzon vlerësimin; shënimi shfaqet publikisht te profili i medias.
2. Shkalla majtas–djathtas është ajo e Ground News. Nëse për mediat shqip ka më shumë kuptim një bosht tjetër (p.sh. *pro-qeverisë / kritike ndaj qeverisë*), mund të ndryshohen vetëm etiketat te `frontend/src/shared/model/ratings.ts` dhe të shpjegohet te faqja e metodologjisë.
3. Pas ndryshimit: commit + deploy (hapi `migrate` i sinkronizon). Vlerësimet vlejnë menjëherë për të gjitha historitë.

### Kontrolli i grupimit të historive

Grupimi bëhet automatikisht me çdo run: çdo 30 minuta pa server (Pjesa B), çdo 15 minuta në server (Pjesa C). Për të parë si po punon me lajmet reale, në server:

```bash
gj stories-review --hours 48        # historitë me disa media, anëtarët më të dobët, "gati-bashkimet"
```

Workflow-i *Source validation* në GitHub e publikon të njëjtin raport për feed-et reale, pa server. Nëse historitë bashkojnë ngjarje të ndryshme, rrite `STORY_SIMILARITY_THRESHOLD` te `.env` (p.sh. 0.5) dhe `STORY_MEMBER_SIMILARITY_THRESHOLD` (p.sh. 0.6); nëse i ndajnë shumë, uli (p.sh. 0.4 dhe 0.45). Pastaj `gj cluster --rebuild-days 3`.

---

## Kur ta kalosh nga falas te Claude

**Pa server (Pjesa B):** shto secret-in `ANTHROPIC_API_KEY` te GitHub, pastaj **Actions → Free hosting → Run workflow → task: `reanalyse`** (hapi B6).

**Në server (Pjesa C),** te `/opt/gjurme`:

```bash
nano .env                                   # vendos 4 rreshtat e mënyrës "Me Claude" nga hapi C8
./deploy.sh "$(cat .deploy-state/current)"  # rinis kontejnerët me .env-in e ri (me kontroll shëndeti)
IMAGE_TAG=$(cat .deploy-state/running) docker compose -f docker-compose.prod.yml \
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
| `model` | `gemma3:4b`, ose `gemma3:12b`: shqipja e përmbledhjeve të tij është shumë më e mirë, por është rreth 3 herë më i ngadaltë. `qwen3:4b` nuk funksionon: e harxhon gjithë hapësirën e përgjigjes duke “menduar” |
| `enrich_limit` | `15` |

Pas 10–20 minutash, te **Summary** e sheh për çdo lajm temën, tonin, emrat dhe përmbledhjen, si dhe sa sekonda iu desh modelit për një lajm. Krahasoje me raportin e Claude-it (Pjesa A) dhe me rregullat.

### 2. Modeli lokal në serverin Oracle

Modeli kërkon më shumë memorie se sa aplikacioni vetë. Në hapin C3 zgjidh **2 OCPU dhe 12 GB** (i gjithë limiti falas). Nëse VM-ja është krijuar me 4 GB, ndryshoja madhësinë te Oracle: *Instance → Edit → Shape*.

Në server, te `/opt/gjurme`:

```bash
nano .env        # shto: COMPOSE_PROFILES=local-llm   (LLM_PROVIDER mbetet fake për momentin)
./deploy.sh "$(cat .deploy-state/current)"
alias dc='IMAGE_TAG=$(cat .deploy-state/running) docker compose -f docker-compose.prod.yml'
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
