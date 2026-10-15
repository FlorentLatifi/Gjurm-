"""Synthetic demo dataset — local development, screenshots and end-to-end tests only.

* Sources are fictional (``demo-*`` slugs, ``.invalid`` domains — RFC 2606, cannot resolve).
* People are fictional; places and generic institutions are real nouns used in generic events.
* Refuses to run in staging/production (``Settings.is_deployed``).

The generator writes *raw* feed items with back-dated ``first_seen_at`` and then lets the real
PROCESS, ENRICH (with the fake heuristic provider) and CLUSTER stages do the rest, so demo data
exercises exactly the same code paths as production data. Built-in trends — an election surge in
the last week and a spike for one person in the last day — give the trend detectors something to
find. Every day also has *events* that several outlets cover with differently worded headlines,
some mostly by one side of the (fictional) ratings, so stories, coverage bars and blindspots
have something to show.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import FeedItem, Source
from gjurme.ingestion.normalize import item_key, sha256_hex
from gjurme.sources.ratings import bias_group

DEMO_SOURCES = (
    ("demo-lajmi", "Lajmi Demo", "XK"),
    ("demo-kronika", "Kronika Demo", "XK"),
    ("demo-ekspres", "Ekspres Demo", "XK"),
    ("demo-tirana", "Tirana Demo", "AL"),
    ("demo-rajoni", "Rajoni Demo", "REG"),
    ("demo-zeri", "Zëri Demo", "XK"),
    ("demo-shkupi", "Shkupi Demo", "MK"),
)
# Fictional ratings of the fictional outlets: (bias, factuality, ownership). One stays unrated.
DEMO_RATINGS: dict[str, tuple[str, str, str]] = {
    "demo-lajmi": ("lean_left", "high", "private"),
    "demo-kronika": ("center", "very_high", "public"),
    "demo-ekspres": ("right", "mixed", "media_group"),
    "demo-tirana": ("lean_right", "high", "private"),
    "demo-rajoni": ("center", "high", "public_international"),
    "demo-zeri": ("left", "mixed", "private"),
    "demo-shkupi": ("unrated", "unrated", "unknown"),
}

PEOPLE = (
    "Arben Krasniqi",
    "Drita Berisha",
    "Luan Gashi",
    "Valbona Hoxha",
    "Besnik Morina",
    "Teuta Shala",
    "Agron Rexhepi",
    "Mimoza Kelmendi",
    "Ilir Dervishi",
    "Blerta Zeqiri",
)
PLACES = (
    "Prishtinë",
    "Prizren",
    "Mitrovicë",
    "Pejë",
    "Gjakovë",
    "Ferizaj",
    "Tiranë",
    "Durrës",
    "Shkodër",
    "Vlorë",
    "Shkup",
    "Beograd",
)
SPIKE_PERSON = "Blerta Zeqiri"

TEMPLATES: dict[str, tuple[tuple[str, str], ...]] = {
    "politics": (
        (
            "{p} kërkon seancë të jashtëzakonshme në Kuvend",
            "Deputetja {p} tha se Kuvendi duhet të mblidhet urgjentisht për buxhetin.",
        ),
        (
            "Qeveria miraton {n} projektligje, mes tyre për administratën në {c}",
            "Ministri {p} deklaroi se reforma do të zbatohet nga viti i ardhshëm.",
        ),
        (
            "{p}: Opozita akuzon Qeverinë për vonesa në reforma",
            "{p} tha në Prishtinë se premtimet nuk janë mbajtur.",
        ),
    ),
    "elections": (
        (
            "KQZ certifikon listat e kandidatëve për zgjedhjet në {c}",
            "Komisioni Qendror i Zgjedhjeve njoftoi se fushata nis javën e ardhshme.",
        ),
        (
            "{p} prezanton programin zgjedhor në {c}",
            "Kandidati {p} premtoi vende të reja pune dhe investime në infrastrukturë.",
        ),
        (
            "Debat i ashpër mes kandidatëve për kryetar të {c}",
            "{p} dhe kundërkandidati i tij u përplasën për çështjen e ujit.",
        ),
    ),
    "kosovo_serbia": (
        (
            "Raundi i {n}-të i dialogut Kosovë–Serbi, {p} në Bruksel",
            "Negociatori {p} tha se marrëveshja për energjinë është temë kryesore.",
        ),
        (
            "Tensione në veri pas vendosjes së barrikadave pranë {c}",
            "Policia e Kosovës njoftoi se situata është nën kontroll.",
        ),
    ),
    "economy": (
        (
            "Rriten çmimet e ushqimeve në {c} për {n} për qind",
            "Sipas Agjencisë së Statistikave, inflacioni arriti në 4 për qind.",
        ),
        (
            "Investim i ri prej {n} milionë eurosh në {c}",
            "Kompania premton 300 vende pune, tha {p}.",
        ),
        (
            "Buxheti i vitit 2027 parasheh rritje {n} për qind të pagave",
            "Ministri {p} prezantoi planin fiskal para deputetëve.",
        ),
    ),
    "crime_justice": (
        (
            "Arrestohen {n} persona për kontrabandë në {c}",
            "Policia sekuestroi mallra me vlerë mbi 50 mijë euro.",
        ),
        (
            "Gjykata në {c} dënon ish-zyrtarin me {n} vjet burg për korrupsion",
            "Prokuroria kishte kërkuar dënim prej pesë vitesh për {p}.",
        ),
    ),
    "sports": (
        (
            "FC Prishtina fiton {n}-0, {p} flet pas ndeshjes",
            "Trajneri {p} tha se skuadra luajti ndeshjen më të mirë të sezonit.",
        ),
        (
            "Kombëtarja e Kosovës shpall listën me {n} lojtarë, {p} fton të rinj",
            "Përzgjedhësi {p} ftoi tre lojtarë të rinj.",
        ),
    ),
    "health": (
        (
            "Spitali i {c} merr pajisje të reja diagnostikuese",
            "Drejtori {p} tha se pritjet për ekzaminime do të shkurtohen.",
        ),
        (
            "Rritje e rasteve me grip sezonal në {c}",
            "Instituti Kombëtar i Shëndetësisë Publike rekomandon vaksinimin.",
        ),
    ),
    "education": (
        (
            "Nxënësit e {c} fitojnë medalje në olimpiadën e matematikës",
            "Mësuesja {p} uroi nxënësit për suksesin.",
        ),
        (
            "Universiteti në {c} hap {n} programe të reja në teknologji",
            "Rektori {p} tha se interesimi i studentëve është rritur.",
        ),
    ),
    "eu_integration": (
        (
            "Bashkimi Evropian konfirmon {n} milionë euro për projekte në {c}",
            "Ambasadori {p} tha se reformat duhet të vazhdojnë.",
        ),
    ),
    "accidents_disasters": (
        (
            "Aksident trafiku në magjistralen {c}–Prishtinë, dy të plagosur",
            "Policia njoftoi se rruga ishte e rrëshqitshme.",
        ),
        (
            "Zjarr në një ndërtesë banimi në {c}",
            "Zjarrfikësit e shuan zjarrin pa pasur të lënduar.",
        ),
    ),
    "culture_entertainment": (
        (
            "Festivali i filmit në {c} hap dyert për publikun",
            "Drejtoresha {p} prezantoi programin me 40 filma.",
        ),
    ),
    "environment_energy": (
        (
            "Ndotja e ajrit në {c} arrin nivele alarmante",
            "Ekspertët rekomandojnë kufizimin e qarkullimit të veturave.",
        ),
        (
            "KEK njofton reduktime të rrymës në {c} për {n} orë",
            "Zëdhënësi {p} tha se problemi do të rregullohet sot.",
        ),
    ),
    "infrastructure_transport": (
        (
            "Nis ndërtimi i autostradës drejt {c}",
            "Projekti pritet të përfundojë brenda dy vitesh, tha {p}.",
        ),
    ),
    "diaspora": (
        (
            "Mërgimtarët kthehen për pushime, {n} orë pritje në kufi te {c}",
            "Policia kufitare apelon për durim në pikën e {c}.",
        ),
    ),
    "technology_science": (
        (
            "Startup-i nga {c} fiton çmim ndërkombëtar për inteligjencë artificiale",
            "Themeluesja {p} tha se aplikacioni ndihmon fermerët.",
        ),
    ),
}

# Events that several outlets cover on the same day, each outlet with its own wording. Slots:
# {p} person, {c} place, {n} number, {m} magnitude. Fixed per event, so the wordings agree on
# the facts like real coverage of one event does.
EVENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "fiscal_package": (
        (
            "Qeveria miraton paketën fiskale prej {n} milionë eurosh",
            "Ministri {p} tha se paketa fiskale synon familjet me të ardhura të ulëta.",
        ),
        (
            "{p}: Paketa fiskale prej {n} milionë eurosh nis muajin e ardhshëm",
            "Qeveria miratoi sot paketën fiskale në mbledhjen e kabinetit.",
        ),
        (
            "Miratohet paketa fiskale, {n} milionë euro për familjet",
            "Sipas ministrit {p}, paketa fiskale ndihmon familjet në nevojë.",
        ),
        (
            "Paketa fiskale e Qeverisë: {n} milionë euro, {p} jep detajet",
            "Paketa fiskale u miratua pa votat e opozitës.",
        ),
    ),
    "local_results": (
        (
            "KQZ shpall rezultatet në {c}, {p} prin me {n} për qind",
            "Numërimi i votave në {c} vazhdoi gjatë gjithë natës.",
        ),
        (
            "{p} fiton zgjedhjet për kryetar të {c}",
            "Sipas KQZ-së, {p} mori {n} për qind të votave në {c}.",
        ),
        (
            "Rezultatet në {c}: {p} shpallet fitues me {n} për qind",
            "Komisioni Qendror i Zgjedhjeve publikoi rezultatet për {c}.",
        ),
        (
            "Festë në {c} pas fitores së {p} në zgjedhje",
            "Mbështetësit e {p} dolën në sheshin e {c} pas shpalljes së rezultateve.",
        ),
    ),
    "brussels_dialogue": (
        (
            "Takim në Bruksel: {p} dhe negociatori serb diskutojnë për energjinë",
            "Raundi i ri i dialogut Kosovë–Serbi u mbajt sot në Bruksel.",
        ),
        (
            "Dialogu në Bruksel përfundon pa marrëveshje për energjinë, thotë {p}",
            "{p} deklaroi pas takimit në Bruksel se pala serbe refuzoi propozimin.",
        ),
        (
            "{p} pas takimit në Bruksel: Serbia bllokon marrëveshjen për energjinë",
            "Takimi i dialogut në Bruksel zgjati katër orë.",
        ),
    ),
    "fuel_prices": (
        (
            "Rritet çmimi i naftës në {c}, litri {n} centë më shtrenjtë",
            "Pronarët e pikave të karburantit në {c} thonë se rritja vjen nga bursat.",
        ),
        (
            "Shtrenjtohet nafta në {c}: {n} centë më shumë për litër",
            "Qytetarët e {c} ankohen për çmimin e naftës.",
        ),
        (
            "Nafta më e shtrenjtë në {c}, rritje prej {n} centësh për litër",
            "Shoqata e konsumatorëve kërkon kontroll të çmimit të naftës në {c}.",
        ),
    ),
    "director_arrest": (
        (
            "Arrestohet ish-drejtori {p} në {c} për korrupsion",
            "Prokuroria dyshon se {p} ka keqpërdorur {n} mijë euro.",
        ),
        (
            "{p} në pranga, akuzohet për korrupsion me {n} mijë euro",
            "Policia e arrestoi ish-drejtorin {p} në {c}.",
        ),
        (
            "Prokuroria urdhëron arrestimin e {p} në {c}",
            "Ish-drejtori {p} dyshohet për korrupsion në vlerë {n} mijë euro.",
        ),
        (
            "Rasti {p}: ish-drejtori arrestohet në {c} për korrupsion",
            "Hetimi për korrupsion ndaj {p} nisi vitin e kaluar.",
        ),
    ),
    "earthquake": (
        (
            "Tërmet {m} ballë në {c}, banorët dalin në rrugë",
            "Sizmologët regjistruan tërmetin në {c} pak pas mesnatës.",
        ),
        (
            "Lëkundje tërmeti {m} ballë në {c}, nuk ka të lënduar",
            "Tërmeti u ndje fort në {c} dhe në fshatrat përreth.",
        ),
        (
            "{c} zgjohet nga tërmeti, dëme të lehta në ndërtesa",
            "Kryetari {p} tha se ekipet po vlerësojnë dëmet nga tërmeti {m} ballë.",
        ),
    ),
    "national_team": (
        (
            "Kosova mposht Rumaninë {n}-0, gol i {p}",
            "Kombëtarja e Kosovës fitoi ndaj Rumanisë në stadiumin e {c}.",
        ),
        (
            "Fitore për Dardanët: {n}-0 ndaj Rumanisë në {c}",
            "Sulmuesi {p} shënoi golin e parë kundër Rumanisë.",
        ),
        (
            "{p} shënon, Kosova fiton ndaj Rumanisë",
            "Ndeshja në {c} përfundoi {n}-0 për Kosovën ndaj Rumanisë.",
        ),
    ),
    "hospital_drugs": (
        (
            "Spitali i {c} mbetet pa ilaçe për kancer",
            "Pacientët në {c} detyrohen t'i blejnë ilaçet vetë, tha drejtori {p}.",
        ),
        (
            "Mungesë e ilaçeve për kancer në spitalin e {c}",
            "Drejtori {p} kërkon ndërhyrje urgjente për ilaçet nga ministria.",
        ),
        (
            "Pacientët me kancer në {c} pa ilaçe, {p} fajëson ministrinë",
            "Spitali i {c} ka {n} pacientë në pritje të terapisë me ilaçe.",
        ),
    ),
    "power_cuts": (
        (
            "KEK njofton reduktime të rrymës në {c} për {n} orë",
            "Zëdhënësi {p} tha se defekti në termocentral po riparohet.",
        ),
        (
            "Reduktime të rrymës në {c}, {n} orë pa energji",
            "Defekt në termocentral, njofton KEK përmes zëdhënësit {p}.",
        ),
        (
            "Pa rrymë në {c}: KEK shpjegon defektin në termocentral",
            "Sipas {p}, rryma rikthehet në {c} pas {n} orësh.",
        ),
    ),
    "border_queues": (
        (
            "Mërgimtarët presin {n} orë në kufirin te {c}",
            "Policia kufitare thotë se fluksi i mërgimtarëve është rekord.",
        ),
        (
            "Kolona të gjata të mërgimtarëve në pikën kufitare te {c}",
            "Mërgimtarët ankohen për pritje deri në {n} orë në kufi.",
        ),
        (
            "Pritje deri {n} orë në kufirin te {c}, mërgimtarët kërkojnë sportele",
            "Zyrtari {p} premtoi hapjen e korsive shtesë në kufi.",
        ),
    ),
    "eu_funds": (
        (
            "BE ndan {n} milionë euro për ujësjellësin e {c}",
            "Ambasadori {p} nënshkroi marrëveshjen për ujësjellësin në {c}.",
        ),
        (
            "{n} milionë euro nga Bashkimi Evropian për ujësjellësin e {c}",
            "Fondet e BE-së shkojnë për ujësjellësin, tha ambasadori {p}.",
        ),
        (
            "Ambasadori {p}: BE investon {n} milionë euro në ujësjellësin e {c}",
            "Marrëveshja për ujësjellësin u nënshkrua sot në {c}.",
        ),
    ),
    "teachers_strike": (
        (
            "Grevë e mësuesve në {c}, shkollat mbyllen",
            "Sindikata e mësuesve kërkon rritje pagash prej {n} për qind, tha {p}.",
        ),
        (
            "Mësuesit e {c} në grevë për paga",
            "{p}: Greva e mësuesve vazhdon derisa pagat të rriten {n} për qind.",
        ),
        (
            "Shkollat e {c} pa mësim, mësuesit hyjnë në grevë",
            "Sindikalisti {p} paralajmëron grevë të gjatë të mësuesve.",
        ),
    ),
    "motorway": (
        (
            "Hapet autostrada drejt {c}, {p} pret shiritin",
            "Segmenti i ri i autostradës është {n} kilometra i gjatë.",
        ),
        (
            "Autostrada e re drejt {c} hapet për qarkullim",
            "Ministri {p} përuroi segmentin e autostradës prej {n} kilometrash.",
        ),
        (
            "{p} përuron autostradën drejt {c}",
            "Udhëtimi drejt {c} shkurtohet me autostradën e re prej {n} kilometrash.",
        ),
    ),
    "film_award": (
        (
            "Filmi nga {c} fiton çmimin kryesor në festival",
            "Regjisorja {p} ia dedikoi çmimin e festivalit qytetit të {c}.",
        ),
        (
            "{p} fiton çmimin kryesor me filmin e xhiruar në {c}",
            "Juria e festivalit vlerësoi filmin e {p}.",
        ),
        (
            "Çmim i madh në festival për regjisoren {p} nga {c}",
            "Filmi i {p} mori çmimin kryesor të festivalit.",
        ),
    ),
}
# Which side an event's coverage leans to: most events are covered across the spectrum, some
# mostly by one side (these become blindspots).
SLANTS = (("none", 0.6), ("left", 0.2), ("right", 0.2))

BASE_WEIGHTS = {
    "politics": 18,
    "elections": 4,
    "kosovo_serbia": 7,
    "economy": 12,
    "crime_justice": 12,
    "sports": 11,
    "health": 6,
    "education": 4,
    "eu_integration": 4,
    "accidents_disasters": 8,
    "culture_entertainment": 5,
    "environment_energy": 5,
    "infrastructure_transport": 3,
    "diaspora": 2,
    "technology_science": 3,
}


class DemoRefusedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DemoItem:
    source_slug: str
    title: str
    summary: str
    link: str
    published: datetime


def _weights(days_ago: int) -> dict[str, float]:
    w: dict[str, float] = dict(BASE_WEIGHTS)
    if days_ago <= 7:  # campaign season: elections accelerate week over week
        w["elections"] = 4 + (8 - days_ago) * 3.0
    if days_ago <= 3:
        w["environment_energy"] = 12
    return w


def _event_items(
    rng: random.Random,
    day_start: datetime,
    now: datetime,
    counter: int,
    recent: list[set[str]],
) -> tuple[list[DemoItem], int]:
    """Multi-outlet coverage of the day's events (see EVENTS). ``recent`` holds the events of
    the previous two days and is updated with today's."""
    items: list[DemoItem] = []
    weekend = day_start.weekday() >= 5
    # An event recurs at most every third day, so two occurrences never share a story window.
    fresh = sorted(n for n in EVENTS if all(n not in day for day in recent))
    todays = rng.sample(fresh, min(len(fresh), 3 if weekend else 4))
    recent.append(set(todays))
    del recent[:-2]
    for name in todays:
        slant = rng.choices([s for s, _ in SLANTS], [w for _, w in SLANTS])[0]
        weights = []
        for slug, _n, _c in DEMO_SOURCES:
            group = bias_group(DEMO_RATINGS[slug][0])
            if slant == "none":
                weights.append(1.0)
            else:
                weights.append(3.0 if group == slant else 0.6 if group == "center" else 0.15)
        k = rng.choice((2, 3, 3, 4, 4, 5, 6))
        outlets: list[str] = []
        while len(outlets) < k:
            pick = rng.choices([s for s, _, _ in DEMO_SOURCES], weights)[0]
            if pick not in outlets:
                outlets.append(pick)
        slots = {
            "p": rng.choice(PEOPLE[:-1]),
            "c": rng.choice(PLACES),
            "n": rng.randint(2, 40),
            "m": f"{rng.randint(30, 52) / 10:.1f}",
        }
        variants = list(EVENTS[name])
        rng.shuffle(variants)
        start = day_start + timedelta(minutes=rng.randint(0, 14 * 60))
        for i, slug in enumerate(outlets):
            title_t, summary_t = variants[i % len(variants)]
            published = start + timedelta(minutes=0 if i == 0 else rng.randint(10, 8 * 60))
            if published > now:
                published = now - timedelta(minutes=rng.randint(1, 30))
            counter += 1
            items.append(
                DemoItem(
                    slug,
                    title_t.format(**slots),
                    summary_t.format(**slots),
                    f"https://{slug}.invalid/ngjarje/{published:%Y/%m/%d}/{counter}",
                    published,
                )
            )
    return items, counter


def generate(days: int = 30, seed: int = 42, now: datetime | None = None) -> list[DemoItem]:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic data, not security
    event_rng = random.Random(seed * 7919 + 1)  # noqa: S311 - separate stream for events
    recent_events: list[set[str]] = []
    now = now or datetime.now(UTC)
    items: list[DemoItem] = []
    counter = 0
    recent_titles: set[tuple[str, str]] = set()
    for days_ago in range(days, -1, -1):
        if days_ago % 2 == 0:
            recent_titles.clear()
        day_start = (now - timedelta(days=days_ago)).replace(
            hour=6, minute=0, second=0, microsecond=0
        )
        weekend = day_start.weekday() >= 5
        weights = _weights(days_ago)
        topics, topic_w = list(weights), list(weights.values())
        for slug, _name, _country in DEMO_SOURCES:
            n = rng.randint(8, 14) if weekend else rng.randint(14, 24)
            for _ in range(n):
                topic = rng.choices(topics, topic_w)[0]
                title_t, summary_t = rng.choice(TEMPLATES[topic])
                person = (
                    SPIKE_PERSON
                    if (days_ago == 0 and rng.random() < 0.35)
                    else rng.choice(PEOPLE[:-1])
                )
                place = rng.choice(PLACES)
                number = rng.randint(2, 40)
                title = title_t.format(p=person, c=place, n=number)
                summary = summary_t.format(p=person, c=place, n=number)
                if (slug, title) in recent_titles:
                    continue  # real outlets do not repeat identical headlines within days
                recent_titles.add((slug, title))
                published = day_start + timedelta(minutes=rng.randint(0, 16 * 60))
                if published > now:
                    published = now - timedelta(minutes=rng.randint(1, 120))
                counter += 1
                link = f"https://{slug}.invalid/lajme/{published:%Y/%m/%d}/{counter}"
                items.append(DemoItem(slug, title, summary, link, published))
                if rng.random() < 0.05:  # syndicated copy on another demo outlet
                    other = rng.choice([s for s, _, _ in DEMO_SOURCES if s != slug])
                    counter += 1
                    items.append(
                        DemoItem(
                            other,
                            title.replace(" në ", " ne ", 1),
                            summary,
                            f"https://{other}.invalid/artikull/{counter}",
                            published + timedelta(minutes=rng.randint(5, 90)),
                        )
                    )
        events, counter = _event_items(event_rng, day_start, now, counter, recent_events)
        items.extend(events)
    return items


def seed(session: Session, settings: Settings, days: int = 30, seed_value: int = 42) -> int:
    if settings.is_deployed:
        raise DemoRefusedError("demo data cannot be seeded into staging/production")
    sources: dict[str, Source] = {}
    for slug, name, country in DEMO_SOURCES:
        src = session.scalar(select(Source).where(Source.slug == slug))
        if src is None:
            src = Source(
                slug=slug,
                name=name,
                homepage_url=f"https://{slug}.invalid/",
                feed_url=f"https://{slug}.invalid/feed/",
                language="sq",
                country=country,
                is_active=False,
                disabled_reason="synthetic demo source (never fetched)",
                verification_status="unverified",
            )
            bias, factuality, ownership = DEMO_RATINGS[slug]
            src.bias, src.factuality, src.ownership = bias, factuality, ownership
            if bias != "unrated":
                src.ratings_note = "Fictional rating of a fictional demo outlet."
            session.add(src)
            session.flush()
        sources[slug] = src
    rows = []
    for item in generate(days, seed_value):
        payload: dict[str, Any] = {
            "title": item.title,
            "link": item.link,
            "id": item.link,
            "summary": item.summary,
            "published": item.published.isoformat(),
            "published_iso": item.published.isoformat(),
            "author": None,
            "tags": [],
            "content_length": None,
            "language": "sq",
        }
        seen = item.published + timedelta(minutes=7)
        rows.append(
            {
                "source_id": sources[item.source_slug].id,
                "item_key": item_key(item.link, item.link, item.title, item.published.isoformat()),
                "guid": item.link,
                "link": item.link,
                "payload": payload,
                "content_hash": sha256_hex(item.title, item.summary, item.link),
                "first_seen_at": seen,
                "last_seen_at": seen,
            }
        )
    for i in range(0, len(rows), 1000):
        session.execute(insert(FeedItem).values(rows[i : i + 1000]).on_conflict_do_nothing())
    session.flush()
    return len(rows)
