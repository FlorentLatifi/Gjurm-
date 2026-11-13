"""ENRICH stage: ``core.articles`` (pending) → LLM → ``core.enrichments`` + bridges.

Control flow per run::

    kill switch? ─yes→ skip
    queue = pending ∪ failed-with-attempts-left, newest first, ≤ ENRICH_MAX_PER_RUN
            (then, for a model: what the keyword rules analysed provisionally)
    for each article (LLM_BATCH_SIZE of them share one request):
        cache hit (same input hash + prompt + model)?  → reuse, cost 0
        budget.try_reserve(estimate)?  no → stop dispatching (rest stays pending)
        provider.complete → parse/repair/validate → ground entities
        persist (sequentially, main thread): attempt row + current state + bridges
        consecutive failures ≥ threshold → circuit open, stop
        fatal error (auth / unknown model) → stop immediately
        rate limit still hit after the provider's retries → stop, attempts kept
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import Article, ArticleEntity, ArticleTopic, Enrichment, Entity, Source
from gjurme.enrichment.budget import BudgetGuard, spent_today
from gjurme.enrichment.grounding import ground_entities, split_proper_names
from gjurme.enrichment.pricing import Usage, cost_usd, estimate_call_cost, register_price
from gjurme.enrichment.prompt import (
    BATCH_INSTRUCTION,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ArticleInput,
    input_hash,
    render_batch_message,
    render_user_message,
)
from gjurme.enrichment.providers import (
    AnthropicProvider,
    FakeProvider,
    LLMError,
    LLMProvider,
    OpenAICompatibleProvider,
)
from gjurme.enrichment.schema import (
    BATCH_JSON_SCHEMA,
    OUTPUT_JSON_SCHEMA,
    SCHEMA_VERSION,
    EnrichmentOutput,
    InvalidOutputError,
    parse_output,
    split_batch,
)
from gjurme.ingestion.normalize import normalize_key
from gjurme.runtime_settings import enrichment_paused
from gjurme.taxonomy import TOPIC_BY_SLUG

log = logging.getLogger(__name__)

SYSTEM_PROMPT_TOKENS_EST = len(SYSTEM_PROMPT) // 3 + 400  # + schema overhead
RAW_RESPONSE_MAX = 20_000
# Room for one article's answer in a request for several (two summaries, names, labels).
BATCH_OUTPUT_TOKENS_PER_ARTICLE = 600


class ConfigurationError(RuntimeError):
    pass


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        if settings.is_deployed and not settings.allow_fake_llm_in_production:
            raise ConfigurationError("fake LLM provider is not allowed in deployed environments")
        return FakeProvider()
    if settings.llm_provider == "openai_compatible":
        if not settings.llm_base_url:
            raise ConfigurationError("LLM_BASE_URL is not set (e.g. http://ollama:11434/v1)")
        return _openai_compatible(
            settings,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            response_format=settings.llm_response_format,
            requests_per_minute=settings.llm_requests_per_minute,
            reasoning_effort=settings.llm_reasoning_effort,
        )
    if settings.anthropic_api_key is None or not settings.anthropic_api_key.get_secret_value():
        raise ConfigurationError("ANTHROPIC_API_KEY is not set (or set LLM_PROVIDER=fake)")
    return AnthropicProvider(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.llm_model,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_sdk_max_retries,
        base_url=settings.anthropic_base_url,
    )


@dataclass(slots=True)
class EnrichStats:
    queued: int = 0
    queued_upgrades: int = 0  # of those: analysed by the keyword rules, waiting for a model
    batches: int = 0  # requests that carried more than one article
    batch_fallbacks: int = 0  # articles asked for again alone after such a request
    attempted: int = 0
    succeeded: int = 0
    cached: int = 0
    failed: Counter[str] = field(default_factory=Counter)
    entities_dropped_ungrounded: int = 0
    entities_dropped_not_proper: int = 0
    cost_usd: Decimal = Decimal(0)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    latency_ms_total: int = 0
    budget_exhausted: bool = False
    circuit_open: bool = False
    fatal_error: str | None = None
    skipped_reason: str | None = None
    spent_today_usd: Decimal = Decimal(0)
    time_limited: bool = False  # stopped starting calls after ENRICH_MAX_SECONDS
    rate_limited: bool = False  # the provider still said 429 after its retries (quota used up)

    def as_dict(self) -> dict[str, Any]:
        calls = self.attempted - self.cached
        return {
            "queued": self.queued,
            "queued_upgrades": self.queued_upgrades,
            "batches": self.batches,
            "batch_fallbacks": self.batch_fallbacks,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "cached": self.cached,
            "failed": dict(self.failed),
            "failed_total": sum(self.failed.values()),
            "entities_dropped_ungrounded": self.entities_dropped_ungrounded,
            "entities_dropped_not_proper": self.entities_dropped_not_proper,
            "cost_usd": float(self.cost_usd),
            "spent_today_usd": float(self.spent_today_usd),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "avg_latency_ms": round(self.latency_ms_total / calls) if calls > 0 else None,
            "budget_exhausted": self.budget_exhausted,
            "circuit_open": self.circuit_open,
            "fatal_error": self.fatal_error,
            "time_limited": self.time_limited,
            "rate_limited": self.rate_limited,
            "skipped_reason": self.skipped_reason,
        }


@dataclass(frozen=True, slots=True)
class QueueItem:
    article_id: int
    attempts: int
    article: ArticleInput
    input_hash: str
    # The article has the keyword rules' analysis and keeps it if this attempt fails.
    upgrade: bool = False


@dataclass(slots=True)
class CallOutcome:
    item: QueueItem
    estimate: Decimal
    status: str  # succeeded | failed | invalid | refused
    output: EnrichmentOutput | None = None
    flags: dict[str, Any] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    cost: Decimal = Decimal(0)
    latency_ms: int | None = None
    request_id: str | None = None
    raw_text: str | None = None
    error: str | None = None
    error_kind: str | None = None
    fatal: bool = False
    model: str = ""
    # False for all but one article of a request that failed as a whole: one failed request
    # is one failure for the circuit breaker, however many articles it carried.
    counts_for_breaker: bool = True
    batch_fallback: bool = False  # asked for again alone after a request for several


def build_fallback_provider(settings: Settings) -> LLMProvider | None:
    """The second model (LLM_FALLBACK_*), or None when none is configured."""
    if not settings.llm_fallback_base_url:
        return None
    if not settings.llm_fallback_model:
        raise ConfigurationError("LLM_FALLBACK_MODEL is not set (LLM_FALLBACK_BASE_URL is)")
    return _openai_compatible(
        settings,
        base_url=settings.llm_fallback_base_url,
        model=settings.llm_fallback_model,
        api_key=settings.llm_fallback_api_key,
        response_format=settings.llm_fallback_response_format,
        requests_per_minute=settings.llm_fallback_requests_per_minute,
        reasoning_effort=settings.llm_fallback_reasoning_effort,
    )


def _openai_compatible(
    settings: Settings,
    *,
    base_url: str,
    model: str,
    api_key: Any,
    response_format: Any,
    requests_per_minute: int,
    reasoning_effort: Any,
) -> OpenAICompatibleProvider:
    register_price(model, settings.llm_price_input_per_mtok, settings.llm_price_output_per_mtok)
    return OpenAICompatibleProvider(
        base_url=base_url,
        model=model,
        api_key=api_key.get_secret_value() if api_key else None,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_sdk_max_retries,
        response_format=response_format,
        requests_per_minute=requests_per_minute,
        reasoning_effort=reasoning_effort,
    )


# ---------------------------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------------------------
def load_queue(
    session: Session,
    settings: Settings,
    model: str,
    article_ids: Iterable[int] | None = None,
    *,
    upgrade_rules: bool = False,
) -> list[QueueItem]:
    """Articles to analyse, newest first. With ``upgrade_rules`` (a model is asking and
    ENRICH_RULES_UPGRADE_HOURS is set), the articles the keyword rules analysed in those hours
    follow the ones that have no analysis yet."""
    is_upgrade = Article.enrichment_status == "succeeded"
    query = (
        select(
            Article.id,
            Article.enrichment_attempts,
            is_upgrade.label("upgrade"),
            Article.title,
            Article.excerpt,
            Article.published_date,
            Source.name,
        )
        .join(Source, Source.id == Article.source_id)
        .where(Article.is_hidden.is_(False))
    )
    if article_ids is not None:
        query = query.where(Article.id.in_(list(article_ids)))
    else:
        due = [
            Article.enrichment_status == "pending",
            (Article.enrichment_status == "failed")
            & (Article.enrichment_attempts < settings.enrich_max_attempts),
        ]
        if upgrade_rules and settings.enrich_rules_upgrade_hours:
            since = datetime.now(UTC) - timedelta(hours=settings.enrich_rules_upgrade_hours)
            by_rules = select(Enrichment.article_id).where(
                Enrichment.is_current.is_(True), Enrichment.provider == FakeProvider.name
            )
            due.append(
                is_upgrade
                & (Article.enrichment_attempts < settings.enrich_max_attempts)
                & (Article.ingested_at >= since)
                & Article.id.in_(by_rules)
            )
        query = query.where(or_(*due))
    query = query.order_by(is_upgrade, Article.published_at.desc()).limit(
        settings.enrich_max_per_run
    )
    items = []
    for row in session.execute(query):
        art = ArticleInput(
            source_name=row.name, published=row.published_date, title=row.title, excerpt=row.excerpt
        )
        items.append(
            QueueItem(
                row.id,
                row.enrichment_attempts,
                art,
                input_hash(art, model),
                upgrade=article_ids is None and bool(row.upgrade),
            )
        )
    return items


@dataclass(frozen=True, slots=True)
class CachedResult:
    """A stored result another article with identical input can reuse."""

    id: int
    article_id: int
    output: dict[str, Any]


class ResultCache:
    """Results to reuse for identical input (syndicated copies), loaded once per run.

    An article's *own* earlier results are excluded: re-queueing an article means "analyse it
    again" (e.g. a suspected bad output), which a cache hit would silently turn into a no-op.
    One query for the whole queue instead of one per article: from a runner far from the
    database every query is a round trip (ADR-027). Results stored during the run are added,
    so the second copy of a story syndicated twice in one run still reuses the first.
    """

    def __init__(self, session: Session, hashes: Iterable[str], model: str) -> None:
        self._by_hash: dict[str, list[CachedResult]] = {}
        wanted = list(set(hashes))
        if not wanted:
            return
        rows = session.execute(
            select(Enrichment.id, Enrichment.article_id, Enrichment.input_hash, Enrichment.output)
            .where(
                Enrichment.input_hash.in_(wanted),
                Enrichment.prompt_version == PROMPT_VERSION,
                Enrichment.model == model,
                Enrichment.status.in_(("succeeded", "cached")),
                Enrichment.output.is_not(None),
            )
            .order_by(Enrichment.id)
        )
        for r in rows:
            self.add(r.input_hash, CachedResult(r.id, r.article_id, r.output))

    def add(self, ihash: str, result: CachedResult) -> None:
        self._by_hash.setdefault(ihash, []).append(result)

    def find(self, ihash: str, article_id: int) -> CachedResult | None:
        """The newest result for this input from another article."""
        for result in reversed(self._by_hash.get(ihash, [])):
            if result.article_id != article_id:
                return result
        return None


# ---------------------------------------------------------------------------------------------
# Call (worker thread — no DB access)
# ---------------------------------------------------------------------------------------------
def call_llm(provider: LLMProvider, item: QueueItem, estimate: Decimal) -> CallOutcome:
    user = render_user_message(item.article)
    try:
        result = provider.complete(SYSTEM_PROMPT, user, OUTPUT_JSON_SCHEMA)
    except LLMError as exc:
        return CallOutcome(
            item=item,
            estimate=estimate,
            status="refused" if exc.kind == "refused" else "failed",
            usage=exc.usage,
            cost=cost_usd(provider.model, exc.usage),
            raw_text=exc.raw_text,
            error=str(exc)[:1000],
            error_kind=exc.kind,
            fatal=exc.fatal,
            request_id=exc.request_id,
            model=provider.model,
        )
    except Exception as exc:  # defensive: an SDK bug must not kill the stage
        log.exception("unexpected provider error")
        return CallOutcome(
            item=item,
            estimate=estimate,
            status="failed",
            error=f"unexpected: {type(exc).__name__}: {exc}"[:1000],
            error_kind="unexpected",
            model=provider.model,
        )
    outcome = CallOutcome(
        item=item,
        estimate=estimate,
        status="succeeded",
        usage=result.usage,
        # Price by the configured model id: the API may echo a dated snapshot id.
        cost=cost_usd(provider.model, result.usage),
        latency_ms=result.latency_ms,
        request_id=result.request_id,
        raw_text=result.text,
        model=provider.model,
    )
    return _finish(outcome, result.text)


def _finish(outcome: CallOutcome, text: str | None) -> CallOutcome:
    """Parse, repair, validate and ground one article's answer into ``outcome``."""
    item = outcome.item
    try:
        output, flags = parse_output(text)
    except InvalidOutputError as exc:
        outcome.status, outcome.error, outcome.error_kind = "invalid", str(exc)[:1000], "invalid"
        return outcome
    source_text = f"{item.article.title}\n{item.article.excerpt or ''}"
    proper, common = split_proper_names(output.entities)
    if common:
        flags["entities_not_proper"] = [e.name for e in common]
    kept, dropped = ground_entities(proper, source_text)
    if dropped:
        flags["entities_ungrounded"] = [e.name for e in dropped]
    if common or dropped:
        output = output.model_copy(update={"entities": kept})
    outcome.output, outcome.flags = output, flags
    return outcome


def _share(usage: Usage, parts: int) -> list[Usage]:
    """``usage`` of one request divided over the ``parts`` articles it carried (sums exactly)."""

    def split(total: int) -> list[int]:
        return [total // parts + (1 if i < total % parts else 0) for i in range(parts)]

    return [
        Usage(*tokens)
        for tokens in zip(
            split(usage.input_tokens),
            split(usage.output_tokens),
            split(usage.cache_read_tokens),
            split(usage.cache_write_tokens),
            strict=True,
        )
    ]


def _add(a: Usage, b: Usage) -> Usage:
    return Usage(
        a.input_tokens + b.input_tokens,
        a.output_tokens + b.output_tokens,
        a.cache_read_tokens + b.cache_read_tokens,
        a.cache_write_tokens + b.cache_write_tokens,
    )


def call_llm_batch(
    provider: LLMProvider, batch: list[tuple[QueueItem, Decimal]], max_output_tokens: int
) -> list[CallOutcome]:
    """One request for several articles (worker thread — no DB access); one outcome each.

    Each article's answer goes through the same parse, repair, validation and grounding as a
    request of its own. An article whose answer is missing or invalid is asked for again alone,
    as is every article when the request's answer is unusable as a whole (not JSON, cut off,
    declined, rejected): one odd article or a model that cannot follow the batch format must
    not cost the others their analysis. A used-up quota, a configuration error and a failed
    connection are the request's, not the format's: every article gets that failure.
    """
    if len(batch) == 1:
        return [call_llm(provider, *batch[0])]
    shares = [Usage() for _ in batch]
    texts: dict[int, str] = {}
    result = None
    try:
        result = provider.complete(
            SYSTEM_PROMPT + BATCH_INSTRUCTION,
            render_batch_message([item.article for item, _ in batch]),
            BATCH_JSON_SCHEMA,
            max_output_tokens=max_output_tokens,
        )
    except LLMError as exc:
        shares = _share(exc.usage, len(batch))
        if exc.fatal or exc.kind not in ("truncated", "refused", "bad_request"):
            return [
                CallOutcome(
                    item=item,
                    estimate=estimate,
                    status="failed",
                    usage=shares[i],
                    cost=cost_usd(provider.model, shares[i]),
                    raw_text=exc.raw_text if i == 0 else None,
                    error=str(exc)[:1000],
                    error_kind=exc.kind,
                    fatal=exc.fatal,
                    request_id=exc.request_id,
                    model=provider.model,
                    counts_for_breaker=i == 0,
                )
                for i, (item, estimate) in enumerate(batch)
            ]
    except Exception as exc:  # defensive: an SDK bug must not kill the stage
        log.exception("unexpected provider error")
        return [
            CallOutcome(
                item=item,
                estimate=estimate,
                status="failed",
                error=f"unexpected: {type(exc).__name__}: {exc}"[:1000],
                error_kind="unexpected",
                model=provider.model,
                counts_for_breaker=i == 0,
            )
            for i, (item, estimate) in enumerate(batch)
        ]
    else:
        shares = _share(result.usage, len(batch))
        texts = split_batch(result.text, len(batch))
    outcomes = []
    for i, (item, estimate) in enumerate(batch):
        outcome = None
        if result is not None and i + 1 in texts:
            outcome = _finish(
                CallOutcome(
                    item=item,
                    estimate=estimate,
                    status="succeeded",
                    latency_ms=result.latency_ms,
                    request_id=result.request_id,
                    raw_text=texts[i + 1],
                    model=provider.model,
                ),
                texts[i + 1],
            )
        if outcome is None or outcome.status != "succeeded":
            outcome = call_llm(provider, item, estimate)
            outcome.batch_fallback = True
        outcome.usage = _add(outcome.usage, shares[i])
        outcome.cost = cost_usd(provider.model, outcome.usage)
        outcomes.append(outcome)
    return outcomes


# ---------------------------------------------------------------------------------------------
# Persistence (main thread)
# ---------------------------------------------------------------------------------------------
def _upsert_entities(session: Session, output: EnrichmentOutput) -> list[int]:
    wanted: dict[tuple[str, str], str] = {}
    for ent in output.entities:
        key = normalize_key(ent.name)
        if key:
            wanted.setdefault((ent.type, key), ent.name)
    if not wanted:
        return []
    # One round trip: insert the new names, and read the ids of new and existing ones together.
    rows = [{"type": t, "normalized_key": k, "name": n} for (t, k), n in wanted.items()]
    inserted = (
        insert(Entity)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[Entity.type, Entity.normalized_key])
        .returning(Entity.id, Entity.type, Entity.normalized_key)
        .cte("inserted")
    )
    existing = select(Entity.id, Entity.type, Entity.normalized_key).where(
        Entity.normalized_key.in_([k for _, k in wanted]),
        Entity.type.in_({t for t, _ in wanted}),
    )
    found = session.execute(
        select(inserted.c.id, inserted.c.type, inserted.c.normalized_key).union(existing)
    )
    return sorted({r.id for r in found if (r.type, r.normalized_key) in wanted})


def apply_output(
    session: Session, article_id: int, output: EnrichmentOutput, *, attempts: int | None = None
) -> None:
    """Make ``output`` the article's current analysis (denormalized fields + bridges)."""
    now = datetime.now(UTC)
    counted = {} if attempts is None else {"enrichment_attempts": attempts}
    published_date = session.execute(
        update(Article)
        .where(Article.id == article_id)
        .values(
            **counted,
            enrichment_status="succeeded",
            enriched_at=now,
            primary_topic_id=TOPIC_BY_SLUG[output.primary_topic].id,
            sentiment_label=output.sentiment,
            sentiment_score=round(output.sentiment_score, 3),
            event_type=output.event_type,
            detected_language=output.language,
            countries=output.countries,
            summary_en=output.summary_en,
            summary_sq=output.summary_sq,
            enrichment_confidence=round(output.confidence, 3),
        )
        .returning(Article.published_date)
    ).scalar_one()
    # Bridges carry the article's date for windowed index scans (migration 0002).
    session.execute(delete(ArticleTopic).where(ArticleTopic.article_id == article_id))
    topic_rows = [
        {
            "article_id": article_id,
            "topic_id": TOPIC_BY_SLUG[output.primary_topic].id,
            "is_primary": True,
            "published_date": published_date,
        }
    ]
    topic_rows += [
        {
            "article_id": article_id,
            "topic_id": TOPIC_BY_SLUG[s].id,
            "is_primary": False,
            "published_date": published_date,
        }
        for s in output.secondary_topics
    ]
    session.execute(insert(ArticleTopic).values(topic_rows).on_conflict_do_nothing())
    session.execute(delete(ArticleEntity).where(ArticleEntity.article_id == article_id))
    entity_ids = _upsert_entities(session, output)
    if entity_ids:
        session.execute(
            insert(ArticleEntity)
            .values(
                [
                    {"article_id": article_id, "entity_id": eid, "published_date": published_date}
                    for eid in entity_ids
                ]
            )
            .on_conflict_do_nothing()
        )


def persist_outcome(
    session: Session,
    outcome: CallOutcome,
    *,
    run_id: int | None,
    provider_name: str,
    max_attempts: int,
    cached_from: CachedResult | None = None,
) -> int | None:
    """Store a call's outcome; the stored result's id when it succeeded."""
    item = outcome.item
    attempt = item.attempts + 1
    success = outcome.status in ("succeeded", "cached") and outcome.output is not None
    if success:
        session.execute(
            update(Enrichment)
            .where(Enrichment.article_id == item.article_id, Enrichment.is_current.is_(True))
            .values(is_current=False)
        )
    row = Enrichment(
        article_id=item.article_id,
        run_id=run_id,
        provider=provider_name,
        model=outcome.model,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        status=outcome.status,
        attempt=attempt,
        input_hash=item.input_hash,
        input_tokens=outcome.usage.input_tokens,
        output_tokens=outcome.usage.output_tokens,
        cache_read_tokens=outcome.usage.cache_read_tokens,
        cache_write_tokens=outcome.usage.cache_write_tokens,
        cost_usd=outcome.cost,
        latency_ms=outcome.latency_ms,
        request_id=outcome.request_id,
        output=outcome.output.model_dump() if outcome.output else None,
        raw_response=None if success else (outcome.raw_text or "")[:RAW_RESPONSE_MAX] or None,
        error=outcome.error,
        quality_flags=(
            {**outcome.flags, "cached_from": cached_from.id} if cached_from else outcome.flags
        )
        or None,
        is_current=success,
    )
    session.add(row)
    if success:
        assert outcome.output is not None
        apply_output(session, item.article_id, outcome.output, attempts=attempt)
        session.flush()
        return row.id
    if outcome.fatal or outcome.error_kind == "rate_limited":
        # Configuration problem (bad key, unknown model) or a used-up rate limit (a free tier's
        # daily quota): not the article's fault — leave it queued without consuming one of its
        # attempts.
        return None
    # refused → never retry; otherwise retry until attempts are exhausted
    terminal = outcome.status == "refused"
    if item.upgrade:
        # The article keeps the keyword rules' analysis and its status; only the tries count.
        session.execute(
            update(Article)
            .where(Article.id == item.article_id)
            .values(enrichment_attempts=max_attempts if terminal else attempt)
        )
        return None
    session.execute(
        update(Article)
        .where(Article.id == item.article_id)
        .values(enrichment_attempts=attempt, enrichment_status="skipped" if terminal else "failed")
    )
    if attempt >= max_attempts and not terminal:
        log.warning(
            "article exhausted enrichment attempts",
            extra={"article_id": item.article_id, "error": outcome.error},
        )
    return None


# ---------------------------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------------------------
def run_enrichment(
    session_factory: Callable[[], Session],
    settings: Settings,
    provider: LLMProvider,
    *,
    run_id: int | None = None,
    article_ids: Iterable[int] | None = None,
    on_budget_exhausted: Callable[[], None] | None = None,
    max_seconds: float | None = None,
    batch_size: int = 1,
) -> EnrichStats:
    """Analyse the queue with one provider. ``max_seconds`` overrides ENRICH_MAX_SECONDS;
    ``batch_size`` articles share one request (never for the keyword rules)."""
    stats = EnrichStats()
    if not settings.enrichment_enabled:
        stats.skipped_reason = "disabled by ENRICHMENT_ENABLED=false"
        return stats

    with session_factory() as session:
        paused, reason = enrichment_paused(session)
        if paused:
            stats.skipped_reason = f"paused by operator: {reason or 'no reason given'}"
            log.warning("enrichment paused", extra={"reason": reason})
            return stats
        is_model = provider.name != FakeProvider.name
        queue = load_queue(session, settings, provider.model, article_ids, upgrade_rules=is_model)
        stats.spent_today_usd = spent_today(session)
        cache = ResultCache(session, (item.input_hash for item in queue), provider.model)
    stats.queued = len(queue)
    stats.queued_upgrades = sum(item.upgrade for item in queue)
    if not queue:
        return stats
    if not is_model:
        batch_size = 1

    budget = BudgetGuard(
        settings.llm_daily_budget_usd, stats.spent_today_usd, on_exhausted=on_budget_exhausted
    )
    consecutive_failures = 0
    pending: set[Future[list[CallOutcome]]] = set()
    queue_iter = iter(queue)
    stop_dispatch = False
    limit_seconds = settings.enrich_max_seconds if max_seconds is None else max_seconds
    deadline = time.monotonic() + limit_seconds if limit_seconds else None
    # Anthropic prompt caching: a cached system prompt can be read only once the first response
    # has started, and runs are further apart than the cache lives. Sent together, the first
    # calls of a run would each pay a cache write; sent first and alone, one call writes it.
    warm_cache = provider.name == "anthropic"

    def record(outcome: CallOutcome, cached_from: CachedResult | None = None) -> None:
        nonlocal consecutive_failures
        for retry in (False, True):
            try:
                with session_factory() as s, s.begin():
                    stored = persist_outcome(
                        s,
                        outcome,
                        run_id=run_id,
                        provider_name=provider.name,
                        max_attempts=settings.enrich_max_attempts,
                        cached_from=cached_from,
                    )
                if stored is not None and outcome.output is not None:
                    cache.add(
                        outcome.item.input_hash,
                        CachedResult(stored, outcome.item.article_id, outcome.output.model_dump()),
                    )
                break
            except IntegrityError:
                # Another run stored a result for this article meanwhile (two runs at once):
                # record this one again on top of it, so the paid call still counts.
                if retry:
                    raise
                log.warning(
                    "article analysed by two runs at once",
                    extra={"article_id": outcome.item.article_id},
                )
        stats.attempted += 1
        stats.cost_usd += outcome.cost
        stats.input_tokens += outcome.usage.input_tokens
        stats.output_tokens += outcome.usage.output_tokens
        stats.cache_read_tokens += outcome.usage.cache_read_tokens
        stats.latency_ms_total += outcome.latency_ms or 0
        if outcome.status == "cached":
            stats.cached += 1
            return
        if outcome.status == "succeeded":
            stats.succeeded += 1
            stats.entities_dropped_ungrounded += len(outcome.flags.get("entities_ungrounded", []))
            stats.entities_dropped_not_proper += len(outcome.flags.get("entities_not_proper", []))
            consecutive_failures = 0
        else:
            stats.failed[outcome.error_kind or outcome.status] += 1
            # A used-up rate limit stops the stage by itself (below); it says nothing about
            # whether the provider is broken, so it does not trip the circuit breaker.
            if (
                outcome.status != "refused"
                and outcome.error_kind != "rate_limited"
                and outcome.counts_for_breaker
            ):
                consecutive_failures += 1

    with ThreadPoolExecutor(
        max_workers=settings.enrich_concurrency, thread_name_prefix="enrich"
    ) as pool:
        while True:
            # Fill the worker pool: each worker takes one request of up to batch_size articles.
            limit = 1 if warm_cache else settings.enrich_concurrency
            while not stop_dispatch and len(pending) < limit:
                batch: list[tuple[QueueItem, Decimal]] = []
                while len(batch) < batch_size:
                    if deadline is not None and time.monotonic() > deadline:
                        stats.time_limited = stop_dispatch = True
                        log.info(
                            "enrichment time limit reached; the rest waits for the next run",
                            extra={"max_seconds": settings.enrich_max_seconds},
                        )
                        break
                    item = next(queue_iter, None)
                    if item is None:
                        stop_dispatch = True
                        break
                    cached = cache.find(item.input_hash, item.article_id)
                    if cached is not None:
                        out = EnrichmentOutput.model_validate(cached.output)
                        record(
                            CallOutcome(
                                item=item,
                                estimate=Decimal(0),
                                status="cached",
                                output=out,
                                model=provider.model,
                            ),
                            cached_from=cached,
                        )
                        continue
                    estimate = estimate_call_cost(
                        provider.model,
                        len(item.article.title) + len(item.article.excerpt or ""),
                        SYSTEM_PROMPT_TOKENS_EST,
                        settings.llm_max_output_tokens,
                    )
                    if not budget.try_reserve(estimate):
                        stats.budget_exhausted = True
                        stop_dispatch = True
                        log.warning(
                            "daily LLM budget reached",
                            extra={
                                "budget_usd": float(budget.budget),
                                "spent_usd": float(budget.spent),
                            },
                        )
                        break
                    batch.append((item, estimate))
                if batch:
                    stats.batches += len(batch) > 1
                    room = max(
                        settings.llm_max_output_tokens,
                        BATCH_OUTPUT_TOKENS_PER_ARTICLE * len(batch),
                    )
                    pending.add(pool.submit(call_llm_batch, provider, batch, room))
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for outcome in (o for fut in done for o in fut.result()):
                warm_cache = False
                stats.batch_fallbacks += outcome.batch_fallback
                budget.settle(outcome.estimate, outcome.cost)
                record(outcome)
                if outcome.fatal and not stats.fatal_error:
                    stats.fatal_error = outcome.error
                    stop_dispatch = True
                    log.error(
                        "fatal LLM error — stopping enrichment", extra={"error": outcome.error}
                    )
                if outcome.error_kind == "rate_limited" and not stats.rate_limited:
                    # The provider already retried with backoff: the quota is used up for now,
                    # and every further call would fail the same way. The rest waits.
                    stats.rate_limited = stop_dispatch = True
                    log.warning(
                        "LLM rate limit reached; the rest waits for the next run",
                        extra={"error": outcome.error},
                    )
                if (
                    consecutive_failures >= settings.enrich_circuit_breaker_threshold
                    and not stats.circuit_open
                ):
                    stats.circuit_open = True
                    stop_dispatch = True
                    log.error(
                        "enrichment circuit breaker opened",
                        extra={"consecutive_failures": consecutive_failures},
                    )
    stats.spent_today_usd = budget.spent
    log.info("enrichment done", extra=stats.as_dict())
    return stats


RULES_FALLBACK_MAX = 2000  # articles per run; the rules take milliseconds each


def enrich_stage(
    session_factory: Callable[[], Session],
    settings: Settings,
    provider: LLMProvider,
    *,
    run_id: int | None = None,
) -> dict[str, Any]:
    """The ENRICH stage: the configured model, then the fallback model, then the rules.

    The fallback model (LLM_FALLBACK_*) takes over when the first model stops early: its quota
    is used up (429), it keeps failing (circuit breaker) or it is misconfigured. It gets the
    time left of ENRICH_MAX_SECONDS. Then any article that no model analysed within
    ENRICH_RULES_AFTER_MINUTES gets the keyword-rule analysis. The returned stats are the first
    model's, with ``fallback`` and ``rules`` added when those ran, so alerts and the run status
    still describe the configured model.
    """
    started = time.monotonic()
    stats = run_enrichment(
        session_factory, settings, provider, run_id=run_id, batch_size=settings.llm_batch_size
    )
    result: dict[str, Any] = stats.as_dict()
    fallback = None if provider.name == "fake" else build_fallback_provider(settings)
    if fallback is not None and (stats.rate_limited or stats.circuit_open or stats.fatal_error):
        remaining: float | None = None
        if settings.enrich_max_seconds:
            remaining = settings.enrich_max_seconds - (time.monotonic() - started)
        if remaining is None or remaining > 30:
            log.info(
                "first model stopped early; the fallback model takes the rest",
                extra={"fallback_model": fallback.model},
            )
            result["fallback"] = run_enrichment(
                session_factory,
                settings,
                fallback,
                run_id=run_id,
                max_seconds=remaining or 0,
                batch_size=settings.llm_fallback_batch_size,
            ).as_dict()
    if settings.enrich_rules_after_minutes and provider.name != "fake":
        with session_factory() as session:
            ids = rules_fallback_due(session, settings)
        if ids:
            rules_settings = settings.model_copy(
                update={"enrich_max_per_run": len(ids), "enrich_max_seconds": 0}
            )
            result["rules"] = run_enrichment(
                session_factory, rules_settings, FakeProvider(), run_id=run_id, article_ids=ids
            ).as_dict()
            log.info(
                "articles no model analysed in time got the keyword-rule analysis",
                extra={"articles": len(ids), "after_minutes": settings.enrich_rules_after_minutes},
            )
    return result


def rules_fallback_due(session: Session, settings: Settings) -> list[int]:
    """Articles still without any analysis ENRICH_RULES_AFTER_MINUTES after ingestion, or at
    once when the rules' analysis is provisional (ENRICH_RULES_UPGRADE_HOURS): the article then
    stays queued for a model, so nothing is gained by keeping it out of its story meanwhile.

    Articles that have an analysis and wait for a better one (``enrich-requeue``) are left to
    the model: they keep showing the analysis they have meanwhile.
    """
    wait_minutes = 0 if settings.enrich_rules_upgrade_hours else settings.enrich_rules_after_minutes
    waited = datetime.now(UTC) - timedelta(minutes=wait_minutes)
    analysed = select(Enrichment.article_id).where(Enrichment.is_current.is_(True))
    return list(
        session.scalars(
            select(Article.id)
            .where(
                Article.is_hidden.is_(False),
                Article.enrichment_status.in_(("pending", "failed")),
                Article.ingested_at < waited,
                Article.id.not_in(analysed),
            )
            .order_by(Article.published_at.desc())
            .limit(RULES_FALLBACK_MAX)
        )
    )


def requeue(
    session: Session,
    *,
    older_than_prompt: str | None = None,
    article_ids: list[int] | None = None,
    include_failed: bool = False,
    provider: str | None = None,
) -> int:
    """Mark articles for re-enrichment (new prompt/model, or manual reprocess).

    ``provider`` selects articles whose current analysis came from that provider, e.g. ``fake``
    (keyword rules) to re-analyse them with Claude once an API key is configured.
    """
    conditions = []
    if article_ids:
        conditions.append(Article.id.in_(article_ids))
    if older_than_prompt:
        current_versions = select(Enrichment.article_id).where(
            Enrichment.is_current.is_(True), Enrichment.prompt_version < older_than_prompt
        )
        conditions.append(Article.id.in_(current_versions))
    if include_failed:
        conditions.append(Article.enrichment_status.in_(("failed", "skipped")))
    if provider:
        by_provider = select(Enrichment.article_id).where(
            Enrichment.is_current.is_(True), Enrichment.provider == provider
        )
        conditions.append(Article.id.in_(by_provider))
    if not conditions:
        raise ValueError("requeue needs at least one selector")
    result = session.execute(
        update(Article)
        .where(or_(*conditions))
        .values(enrichment_status="pending", enrichment_attempts=0)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
