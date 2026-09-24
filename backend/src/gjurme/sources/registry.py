"""Source registry: typed loading of ``sources.yaml`` and idempotent sync into ``core.sources``."""

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from gjurme.db.models import Source
from gjurme.ingestion.normalize import validate_public_http_url

log = logging.getLogger(__name__)


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1)
    homepage_url: str
    feed_url: str | None = None
    discovery_urls: tuple[str, ...] = ()
    language: str = Field(pattern=r"^[a-z]{2}$")
    country: str = Field(pattern=r"^([A-Z]{2}|REG)$")
    enabled: bool = True
    notes: str = ""

    @field_validator("homepage_url", "feed_url")
    @classmethod
    def _public_url(cls, value: str | None) -> str | None:
        return None if value is None else validate_public_http_url(value)

    @field_validator("discovery_urls")
    @classmethod
    def _public_urls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(validate_public_http_url(v) for v in value)

    @model_validator(mode="after")
    def _enabled_needs_feed(self) -> SourceConfig:
        if self.enabled and not self.feed_url:
            raise ValueError(f"source {self.slug!r} is enabled but has no feed_url")
        return self


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[SourceConfig]

    @model_validator(mode="after")
    def _unique_slugs(self) -> Registry:
        slugs = [s.slug for s in self.sources]
        dupes = {s for s in slugs if slugs.count(s) > 1}
        if dupes:
            raise ValueError(f"duplicate source slugs: {sorted(dupes)}")
        return self


def load_registry(path: Path | None = None) -> Registry:
    if path is None:
        text = resources.files("gjurme.sources").joinpath("sources.yaml").read_text("utf-8")
    else:
        text = path.read_text("utf-8")
    return Registry.model_validate(yaml.safe_load(text))


def sync_sources(session: Session, registry: Registry) -> dict[str, int]:
    """Upsert registry entries into ``core.sources``.

    The YAML owns *configuration* (name, URLs, language, country). Runtime state (failure
    counters, conditional-GET validators, verification status) is owned by the pipeline and is
    never overwritten here. A source disabled at runtime (auto-disable / admin) stays disabled
    until an operator re-enables it; ``enabled: false`` in YAML always wins.
    """
    existing = {s.slug: s for s in session.scalars(select(Source))}
    created = updated = 0
    for cfg in registry.sources:
        row = existing.get(cfg.slug)
        if row is None:
            row = Source(
                slug=cfg.slug,
                name=cfg.name,
                homepage_url=cfg.homepage_url,
                feed_url=cfg.feed_url,
                language=cfg.language,
                country=cfg.country,
                is_active=cfg.enabled,
                disabled_reason=None if cfg.enabled else "disabled in sources.yaml",
            )
            session.add(row)
            created += 1
            continue
        changed = False
        for attr in ("name", "homepage_url", "language", "country"):
            if getattr(row, attr) != getattr(cfg, attr):
                setattr(row, attr, getattr(cfg, attr))
                changed = True
        if row.feed_url != cfg.feed_url:
            row.feed_url = cfg.feed_url
            row.etag = row.last_modified = None  # validators belong to the old URL
            row.consecutive_failures = 0
            row.verification_status = "unverified"
            changed = True
        if not cfg.enabled and row.is_active:
            row.is_active = False
            row.disabled_reason = "disabled in sources.yaml"
            changed = True
        elif (
            cfg.enabled and not row.is_active and row.disabled_reason == "disabled in sources.yaml"
        ):
            row.is_active = True
            row.disabled_reason = None
            changed = True
        updated += int(changed)
    session.flush()
    log.info("sources synced", extra={"sources_created": created, "sources_updated": updated})
    return {"created": created, "updated": updated}
