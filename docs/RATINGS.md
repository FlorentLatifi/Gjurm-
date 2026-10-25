# Outlet ratings review — 2026-10-25

The perspective, factuality and ownership of the 19 enabled outlets, with what each rating rests on. The ratings themselves live in [`sources.yaml`](../backend/src/gjurme/sources/sources.yaml), each with a short `ratings_note` that the outlet's page shows. This file holds the method and the evidence behind them ([ADR-021](DECISIONS.md#adr-021-outlet-ratings-are-editorial-declared-with-their-basis-unrated-by-default), [ADR-031](DECISIONS.md#adr-031-perspective-in-albanian-language-media-means-closeness-to-the-two-political-camps)).

The review was AI-assisted and commissioned by the operator. It is an editorial judgement about each **outlet**, never about a single article. Outlets and readers can ask for a correction through the contact on the methodology page. **Next review: January 2027**, with at least 60 days of headlines (this one had 5).

## Summary

| Outlet | Country | Perspective | Factuality | Ownership | Confidence |
|---|---|---|---|---|---|
| Telegrafi | XK | center | high | media group (Lluka family) | medium |
| KOHA | XK | center | high | media group (Flaka Surroi) | medium |
| Gazeta Express | XK | center | mixed | media group (Media Works) | low / medium |
| Kallxo | XK | center | high | non-profit (BIRN Kosovo) | high |
| Radio Evropa e Lirë | XK | center | high | international public (RFE/RL) | high |
| Reporteri.net | XK | center | unrated | private (not documented) | low |
| Zëri | XK | center | unrated | private (Blerim Shala) | low |
| Dukagjini | XK | center | unrated | media group (Lluka family) | low |
| Indeksonline | XK | center | mixed | private (Faton Shoshi) | low / medium |
| Lajmi.net | XK | center | unrated | private (not documented) | low |
| Sinjali | XK | center | unrated | private (not documented) | low |
| Hibrid.info | XK | center | very high | non-profit (ADS) | high |
| Ekonomia Online | XK | center | unrated | private (not documented) | low |
| Reporter.al | AL | center | high | non-profit (BIRN Albania) | high |
| Euronews Albania | AL | **lean left** | unrated | private (Inter Media Group) | medium |
| BalkanWeb | AL | **lean right** | unrated | media group (Focus Group) | medium |
| RTSH | AL | **lean left** | unrated | public broadcaster | medium |
| Faktoje.al | AL | center | very high | non-profit | high |
| Portalb.mk | MK | center | high | private | low |

**What this means on the site:**
- **Albania:** stories now show a real left/right split, because three of the five Albanian outlets lean one way or the other.
- **Kosovo:** almost every outlet is rated center, so Kosovo stories are mostly grey and perspective blindspots are rare. That is the finding, not a gap. In their news headlines, Kosovo's portals mostly report each party's statements and do not frame them. Where they differ is in what they choose to cover and in their opinion pieces, which headlines alone cannot measure. The January review should add opinion pages.

## Method

### Perspective: closeness to the two political camps

On Ground News, left and right are the US parties. Here the scale measures how close an outlet stands to the two political camps of its country:

| Country | Left | Right |
|---|---|---|
| Kosovo | Vetëvendosje (LVV) | PDK, LDK, AAK |
| Albania | Socialist Party (PS) | Democratic Party (PD) |
| North Macedonia (Albanian-language parties) | — | — |

In Kosovo and in Albania alike, the left party governs in October 2026. "Lean left" therefore currently also means "closer to the government". The scale follows the parties, not the government of the day, so it stays meaningful when governments change.

An outlet leans when at least two of these point the same way:
1. **Ownership and documented ties:** owners or editors who held party office, or a public conflict with one camp.
2. **Framing in its own headlines:** whose claims it states as fact or relays without the other side, and whose words it uses (for example "regime" or "the mother of violence").
3. **Balance:** how much space each camp gets on the same events.

One signal alone is noted in the outlet's rating note but does not move the rating. Zëri's owner is an example.

### The headline sample

All headlines from **21–25 October 2026** (the data then available) that name a party or its leader, taken from GJURMË's public API:

```
GET https://gjurm.vercel.app/api/v1/articles?source=<slug>&days=30&q=<term>&page_size=40
```

The search terms:
- **Kosovo:** `kurti`, `vetevendosje`, `osmani`, `pdk`, `hamza`, `ldk`, `abdixhiku`, `haradinaj`.
- **Albania:** `rama`, `socialist`, `berisha`, `demokrat`, `veliaj`, `balluku`.
- **North Macedonia:** `mickoski`, `vmro`, `bdi`, `ahmeti`, `vlen`.

The sample has 536 headlines. Each one was read and classed as *relays one side*, *frames one side negatively* or *neutral / both sides*. Off-topic matches (footballers named Osmani, Kosovo politicians named Rama) were set aside.

The window was dominated by two events: the PDK leadership crisis in Kosovo, and the student protests and Prime Minister Rama's response in Albania. Five days is short, which is why most Kosovo ratings carry low confidence.

### Factuality

| Rating | Evidence needed |
|---|---|
| very high | IFCN signatory or EFCSN member fact-checker with a published methodology and corrections policy |
| high | Established newsroom with documented editorial standards, and no pattern of upheld complaints on truthfulness or of published false claims |
| mixed | Repeated upheld press-council complaints (truthfulness, privacy, right of reply), or documented publication of false claims |
| low / very low | Frequent false or fabricated content (none of the 19) |
| unrated | No record either way. **Not rating is not a judgement.** |

Sources for complaints:
- Kosovo Press Council (KMShK) decisions.
- The Çohu monitoring of 24 online outlets (2020–21).
- NGO complaints decided by the Council.

### Ownership

From the [Media Ownership Monitor](https://kosovo.mom-gmr.org/) (BIRN / Reporters Without Borders) where it covers the outlet, otherwise from the publisher's own pages and press reports. "Not documented" means no public record was found. Kosovo law requires ownership disclosure only from companies registered with the Independent Media Commission, and many portals are not.

## Evidence per outlet

### Telegrafi (XK): center, high
- **Ownership:** the Lluka family, which also owns RTV Dukagjini ([Wikipedia: RTV Dukagjini](https://en.wikipedia.org/wiki/RTV_Dukagjini), citing the Media Ownership Monitor).
- **Headlines (n=19):** statements by Kurti and by Osmani on the Preševo Valley vote, PDK's leadership crisis reported through its own members, and Haradinaj and Limaj criticising PDK. No partisan framing.
- **Complaints:**
  - No complaint in the 2020–21 Çohu monitoring ([Kallxo](https://kallxo.com/lajm/cohu-prezantoi-raportin-per-monitorimin-e-mediave-online/)).
  - In 2025 the Press Council partly upheld an NGO Aktiv complaint against Telegrafi and four other portals, on truthfulness and the right of reply ([NGO Aktiv](https://ngoaktiv.org/en/news/press-council-of-kosovo-confirms-violation-of-truth-reporting-in-the-case-of-ngo-aktiv/)). One case against a very high output.

### KOHA (XK): center, high
- **Ownership:** Flaka Surroi has led and owned Koha Group (KTV, Koha.net) since 2004, after her brother Veton Surroi left for politics ([Wikipedia](https://en.wikipedia.org/wiki/Flaka_Surroi), [EED](https://democracyendowment.eu/stories/flaka-surroi-and-koha)).
- **Her columns:** often critical of the Kurti government.
- **Headlines (n=33):** Kurti's diplomacy and statements reported straight, and PDK's and LDK's internal disputes reported as news. One commentary headline ("PDK needs a new contract with the citizens, not just a new leader") is opinion about the opposition, not for the government.

### Gazeta Express (XK): center (low confidence), mixed
- **Ownership:** Media Works. The Media Ownership Monitor traces it to Media A.B.C. Holding B.V. (Netherlands) and links it to the ABC group ([MOM](https://kosovo.mom-gmr.org/en/media/detail/outlet/gazeta-express-1/)).
- **Political history:** Berat Buzhala, a former PDK member of parliament (2010–13), was its director and its largest shareholder from 2018 to 2021 ([Wikipedia](https://en.wikipedia.org/wiki/Berat_Buzhala)). That history is not visible in today's headlines.
- **Headlines (n=16):** neutral.
- **Factuality:**
  - 18 complaints in the 2020–21 Çohu monitoring, among the most of any outlet.
  - A Press Council finding that it breached the right of reply in an NGO Aktiv case ([NGO Aktiv](https://ngoaktiv.org/en/news/ngo-aktiv-reaction-to-the-press-council-of-kosovo-decisions-on-its-complaints/)).

### Kallxo (XK): center, high
- **Ownership and funding:** non-profit (BIRN Kosovo, Internews Kosova), donor-funded with published partners.
- **Record:** EU Award for Investigative Journalism 2023 for "The purchase of the Chief Prosecutor" ([Prishtina Insight](https://prishtinainsight.com/birn-wins-eu-award-on-investigative-journalism-for-exposing-corruption/)). Its Krypometri fact-checks every party. Rated high credibility by [Media Bias/Fact Check](https://mediabiasfactcheck.com/kallxo-bias-and-credibility/).
- **Headlines (n=5):** neutral.

### Radio Evropa e Lirë (XK): center, high
- **Ownership:** the Albanian-language service of RFE/RL, funded by the US Congress through the USAGM, with a statutory firewall between the funder and the newsroom ([RFE/RL](https://about.rferl.org/service/kosovo-service/)).
- **Headlines (n=4):** attributed and wire-style ("PDK and LDK at war with themselves").

### Reporteri.net (XK): center (low), unrated
- **Ownership:** no public record found.
- **Headlines (n=27):** Kurti's statements, opposition criticism of the Kurti government ("Ymeri: 947 fewer nurses at the university hospital"), and PDK and LDK internal disputes. Balanced.

### Zëri (XK): center (low), unrated
- **Ownership:** Blerim Shala, journalist and publisher ([Wikipedia: Mass media in Kosovo](https://en.wikipedia.org/wiki/Mass_media_in_Kosovo)).
- **Possible tie:** a [Kallxo biography](https://kallxo.com/uncategorized/blerim-shala/) lists him as an AAK vice-president from 2009. Other profiles describe him later as an adviser to the president. His current role is unclear.
- **Headlines (n=8):** neutral.
- **Rating:** one signal only (ownership), so it stays center, to be re-checked in January.

### Dukagjini (XK): center (low), unrated
- **Ownership:** Ekrem Lluka holds the majority; the Lluka family also owns Telegrafi ([Wikipedia](https://en.wikipedia.org/wiki/RTV_Dukagjini)).
- **Headlines (n=26):**
  - Heavy coverage of the PDK crisis, including "Lladrovci: there are corrupt people inside PDK" and "Hoxha: PDK had Hamza as an administrator, not a leader".
  - One framing favourable to the government: "Kurti told them on 5 October, 17 days later PDK 'understands' the law is urgent".
  - It also carries LDK's criticism of PDK.
  - Not enough for a lean in five days.

### Indeksonline (XK): center (low), mixed
- **Ownership:** Faton Shoshi has owned it since 2012, after the founders Fidan Rama and Besnik Ramadanaj sold it ([MOM](https://kosovo.mom-gmr.org/sq/media/detail/outlet/indeks-online-1/)).
- **Headlines (n=14):** neutral.
- **Factuality:** the most complained-about outlet at the Press Council in 2020–21, with 30 complaints of which 18 (60 %) were upheld, mostly on privacy and truthful reporting ([Çohu, via Kallxo](https://kallxo.com/lajm/cohu-prezantoi-raportin-per-monitorimin-e-mediave-online/)).

### Lajmi.net (XK): center (low), unrated
- **Ownership:** no public record found.
- **Headlines (n=30), both directions:**
  - Government framing: "Kurti had warned PDK on 5 October about the law".
  - Opposition pressure: "Gjini asks Kurti to account: why are we excluded from the strategic dialogue with America?" and "The opposition asks Kurti for concrete steps".

### Sinjali (XK): center (low), unrated
- **Ownership:** no public record found.
- **Headlines (n=12):** statement-based, including "Janina Ymeri asks for an inquiry on energy, criticises Kurti for inaction".

### Hibrid.info (XK): center, very high
- **Ownership:** a programme of the NGO Action for Democratic Society since 2020.
- **Standards:** assessed compliant with the IFCN Code of Principles in 2021 and 2023 ([IFCN](https://mail.ifcncodeofprinciples.poynter.org/application/public/action-for-democratic-society-ads-hibridinfo/7A2CEC62-2BD8-CA25-9261-C2E9E3F6F3B2)) and a verified EFCSN member ([EFCSN](https://members.efcsn.com/application/applicationaction-for-democratic-society-ads-hibrid-info70db)).
- **Headlines (n=5):** debunks of false claims about Kurti and about Rama alike.

### Ekonomia Online (XK): center (low), unrated
- **Ownership:** no public record found.
- **Headlines:** business focus. Political headlines (n=12) are statement-based, from all parties.

### Reporter.al (AL): center, high
- **Ownership:** non-profit (BIRN Albania), donor-funded.
- **Record:** one of the outlets ODIHR monitored in the 2025 elections ([ODIHR](https://odihr.osce.org/odihr/elections/albania/584619)).
- **Headlines:** watchdog reporting on the government, such as "SPAK serves Balluku the final charges for five offences" and "Rama announces repressive measures against protesters". It does not advocate for the opposition. Being critical of those in power is a watchdog's job, not a partisan lean.

### Euronews Albania (AL): lean left, unrated
- **Ownership:** Inter Media Group; Vasil Mero 67 %, Theodhor Çami 33 % ([MOM](https://albania.mom-gmr.org/en/media/detail/outlet/euronewsal-1/)).
- **Headlines:** 11 of the 15 on the protests relay Rama's statements and framing:
  - "Rama: violence at the protest by ANTIFA radicals and criminals disguised as students"
  - "Rama: the protest was financed by organised crime and foreign money"
  - "These are not students, they have criminal records"

  The opposition gets 3 (Berisha twice, PD's Gjoni once). Protesters appear mainly through Rama's quotes.
- **Context:** ODIHR found most Albanian outlets are perceived as aligned with the ruling party ([SafeJournalists summary](https://safejournalists.net/media-freedom-under-pressure-osce-odihr-2025-parliamentary-elections-final-report-confirms-structural-threats-to-journalists-and-pluralism-in-albania/)).
- **Rating:** two signals (framing, balance) point the same way.

### BalkanWeb (AL): lean right, unrated
- **Ownership:** Focus Media News, part of Irfan Hysenbelliu's Focus Group, which also owns News24 and Gazeta Shqiptare ([MOM](https://albania.mom-gmr.org/en/media/detail/outlet/balkanwebcom/)).
- **Conflict with the government:** the group has been in open conflict with the Rama government since the 2022 demolition of Hysenbelliu's hotel ([BIRN](https://balkaninsight.com/2022/09/02/albania-media-mogul-claim-government-attacked-his-businesses-over-editorial-line/bi/)).
- **Headlines:** most of the 41 on Rama frame him negatively:
  - "Rama lied shamelessly about Erion"
  - "officially a regime is being installed"
  - "Rama, the one who ordered barbaric violence"

  Opposition and protest voices get prominence.
- **Not the Democratic Party's outlet:** it also runs headlines against Berisha ("Berisha acts as the prime minister's crutch, we have a Rama-Berisha regime"). In May 2026 Berisha attacked the group for allegedly courting Rama ([SafeJournalists](https://safejournalists.net/albania-political-rhetoric-against-media-continues-with-latest-attack-on-news24-panorama-and-balkanweb/)).
- **Rating:** two signals (conflict with the PS government, framing). Lean right, not right.

### RTSH (AL): lean left, unrated
- **Ownership:** the public broadcaster. ODIHR (2025) found that appointments to its governing bodies lack safeguards. IPI and partners are pressing for a "democratic reform" of RTSH ([IPI](https://ipi.media/albania-democratic-reform-of-public-broadcaster/), [SafeJournalists](https://safejournalists.net/albania-rtsh-annual-report-2025-highlights-reform-efforts-but-raises-concerns-on-governance-and-transparency/)).
- **Headlines:** nearly all of the 17 naming Rama relay his statements and framing:
  - "Rama: the Democratic Party is 'the mother of violence'"
  - "Rama publishes data on 45 violent protesters: paid by organised crime"
  - "Rama publishes footage from the meeting with the young man"

  The opposition leader gets 3.
- **Note:** Rama has also criticised RTSH publicly, and its reform with the EBU is ongoing. The rating is about its coverage in October 2026.

### Faktoje.al (AL): center, very high
- **Standards:** Albania's only IFCN signatory, since January 2020 ([Faktoje](https://faktoje.al/faktoje-the-first-organization-in-albania-that-joins-the-international-fact-checking-network)), and an EFCSN member ([EFCSN](https://members.efcsn.com/application/applicationfaktoje0510)).
- **Ownership and funding:** an NGO funded by international donors under a published funding policy.
- **Scope:** checks the statements of every party.

### Portalb.mk (MK): center (low), high
- **Origins:** Albanian-language portal launched in Skopje in 2012 as a project of the Metamorphosis Foundation ([Metamorphosis](https://metamorphosis.org.mk/en/proekti_arhiva/independent-news-portal-in-albanian-portalb-mk/)).
- **Transparency:** publishes its editorial guidelines and a [Journalism Trust Initiative transparency report](https://www.jti-app.com/report/AvPy9exXb1edDqkn/9) (2025).
- **Headlines (n=3):** the opposition SDSM's criticism of Prime Minister Mickoski, and BDI's criticism of a VLEN minister. Both sides covered.

## Limits
- **Five days of headlines.** Event-driven and short. The next review should use at least 60 days and add opinion sections.
- **Headlines, not articles.** GJURMË does not store article text (ADR-003), so story selection and the body of the article are not measured.
- **Four Kosovo outlets have no public ownership record** (Reporteri, Lajmi.net, Sinjali, Ekonomia Online). Their owners could have ties this review cannot see.
- **No numeric "share of left/right".** One person's reading of 536 headlines is a structured judgement, not a measurement. The headline queries above let anyone repeat it.
