"""Controlled vocabularies shared by the LLM output schema, the database seed and the API.

The LLM must choose from these lists (enforced by JSON-schema ``enum`` + Pydantic), which keeps
topic analytics consistent over time. Changing this file is a *prompt/schema change*: bump
``PROMPT_VERSION`` / ``SCHEMA_VERSION`` in ``gjurme.enrichment.prompt``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopicDef:
    id: int
    slug: str
    name_en: str
    name_sq: str
    description: str


TOPICS: tuple[TopicDef, ...] = (
    TopicDef(
        1,
        "politics",
        "Politics & Government",
        "Politikë & Qeverisje",
        "Domestic politics, government, parliament, parties, political conflicts.",
    ),
    TopicDef(
        2,
        "elections",
        "Elections",
        "Zgjedhje",
        "Election campaigns, voting, results, electoral institutions.",
    ),
    TopicDef(
        3,
        "kosovo_serbia",
        "Kosovo–Serbia Relations",
        "Marrëdhëniet Kosovë–Serbi",
        "Dialogue, tensions, the north of Kosovo, Serbian institutions in Kosovo.",
    ),
    TopicDef(
        4,
        "international",
        "International Affairs",
        "Punë të Jashtme",
        "Foreign policy, diplomacy, relations with other states, world news.",
    ),
    TopicDef(
        5,
        "eu_integration",
        "EU & Euro-Atlantic Integration",
        "Integrimi Euroatlantik",
        "EU accession, visa liberalisation, NATO, conditions from Brussels.",
    ),
    TopicDef(
        6,
        "economy",
        "Economy & Business",
        "Ekonomi & Biznes",
        "Economy, prices, budget, taxes, companies, labour market, trade.",
    ),
    TopicDef(
        7,
        "crime_justice",
        "Crime, Justice & Corruption",
        "Krim, Drejtësi & Korrupsion",
        "Crime, police, arrests, courts, prosecution, corruption cases.",
    ),
    TopicDef(
        8,
        "security_defense",
        "Security & Defence",
        "Siguri & Mbrojtje",
        "Armed forces, KFOR, security incidents, terrorism, defence policy.",
    ),
    TopicDef(
        9,
        "health",
        "Health",
        "Shëndetësi",
        "Healthcare system, hospitals, diseases, public health.",
    ),
    TopicDef(
        10,
        "education",
        "Education",
        "Arsim",
        "Schools, universities, students, teachers, education policy.",
    ),
    TopicDef(
        11,
        "society",
        "Society",
        "Shoqëri",
        "Social issues, religion, human rights, gender, social welfare, daily life.",
    ),
    TopicDef(
        12,
        "diaspora",
        "Diaspora & Migration",
        "Diaspora & Migrim",
        "Albanian diaspora, emigration, remittances, migration flows.",
    ),
    TopicDef(
        13,
        "culture_entertainment",
        "Culture & Entertainment",
        "Kulturë & Argëtim",
        "Arts, music, film, celebrities, heritage, lifestyle.",
    ),
    TopicDef(
        14, "sports", "Sports", "Sport", "Football and all other sports, athletes, competitions."
    ),
    TopicDef(
        15,
        "technology_science",
        "Technology & Science",
        "Teknologji & Shkencë",
        "Technology, internet, telecoms, science and research.",
    ),
    TopicDef(
        16,
        "environment_energy",
        "Environment & Energy",
        "Mjedis & Energji",
        "Pollution, climate, weather extremes, electricity, energy supply.",
    ),
    TopicDef(
        17,
        "infrastructure_transport",
        "Infrastructure & Transport",
        "Infrastrukturë & Transport",
        "Roads, construction, public works, traffic, transport.",
    ),
    TopicDef(
        18,
        "accidents_disasters",
        "Accidents & Disasters",
        "Aksidente & Fatkeqësi",
        "Traffic accidents, fires, floods, earthquakes, emergencies.",
    ),
    TopicDef(19, "other", "Other", "Tjetër", "Anything that fits no other topic."),
)

TOPIC_SLUGS: tuple[str, ...] = tuple(t.slug for t in TOPICS)
TOPIC_BY_SLUG: dict[str, TopicDef] = {t.slug: t for t in TOPICS}

EVENT_TYPES: tuple[str, ...] = (
    "statement",  # declarations, interviews, reactions
    "policy_decision",  # government / institutional decisions, laws
    "election_event",
    "protest",
    "investigation_arrest",
    "court_ruling",
    "incident_accident",
    "diplomatic_meeting",
    "report_data",  # statistics, studies, reports
    "sports_result",
    "cultural_event",
    "other",
)

ENTITY_TYPES: tuple[str, ...] = ("person", "organization", "location")
SENTIMENT_LABELS: tuple[str, ...] = ("negative", "neutral", "positive")
LANGUAGES: tuple[str, ...] = ("sq", "en", "sr", "mk", "other")
