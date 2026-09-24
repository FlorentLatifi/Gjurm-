"""Synthetic demo dataset — local development, screenshots and end-to-end tests only.

* Sources are fictional (``demo-*`` slugs, ``.invalid`` domains — RFC 2606, cannot resolve).
* People are fictional; places and generic institutions are real nouns used in generic events.
* Refuses to run in staging/production (``Settings.is_deployed``).

The generator writes *raw* feed items with back-dated ``first_seen_at`` and then lets the real
PROCESS and ENRICH stages (with the fake heuristic provider) do the rest, so demo data exercises
exactly the same code paths as production data. Built-in trends — an election surge in the last
week and a spike for one person in the last day — give the trend detectors something to find.
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

DEMO_SOURCES = (
    ("demo-lajmi", "Lajmi Demo", "XK"),
    ("demo-kronika", "Kronika Demo", "XK"),
    ("demo-ekspres", "Ekspres Demo", "XK"),
    ("demo-tirana", "Tirana Demo", "AL"),
    ("demo-rajoni", "Rajoni Demo", "REG"),
)

PEOPLE = (
    "Arben Krasniqi",
    "Drita Berisha",
    "Luan Gashi",
    "Vlora Hoxha",
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


def generate(days: int = 30, seed: int = 42, now: datetime | None = None) -> list[DemoItem]:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic data, not security
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
