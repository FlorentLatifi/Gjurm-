"""ENRICH stage: ``core.articles`` (pending) → LLM → ``core.enrichments`` + bridges.

Control flow per run::

    kill switch? ─yes→ skip
    queue = pending ∪ failed-with-attempts-left, newest first, ≤ ENRICH_MAX_PER_RUN
    for each article:
        cache hit (same input hash + prompt + model)?  → reuse, cost 0
        budget.try_reserve(estimate)?  no → stop dispatching (rest stays pending)
        provider.complete → parse/repair/validate → ground entities
        persist (sequentially, main thread): attempt row + current state + bridges
        consecutive failures ≥ threshold → circuit open, stop
        fatal error (auth / unknown model) → stop immediately
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import Article, ArticleEntity, ArticleTopic, Enrichment, Entity, Source
from gjurme.enrichment.budget import BudgetGuard, spent_today
from gjurme.enrichment.grounding import ground_entities
from gjurme.enrichment.pricing import Usage, cost_usd, estimate_call_cost
from gjurme.enrichment.prompt import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ArticleInput,
    input_hash,
    render_user_message,
)
from gjurme.enrichment.providers import AnthropicProvider, FakeProvider, LLMError, LLMProvider
from gjurme.enrichment.schema import (
    OUTPUT_JSON_SCHEMA,
    SCHEMA_VERSION,
    EnrichmentOutput,
    InvalidOutputError,
    parse_output,
)
from gjurme.ingestion.normalize import normalize_key
from gjurme.runtime_settings import enrichment_paused
from gjurme.taxonomy import TOPIC_BY_SLUG

log = logging.getLogger(__name__)

SYSTEM_PROMPT_TOKENS_EST = len(SYSTEM_PROMPT) // 3 + 400  # + schema overhead
RAW_RESPONSE_MAX = 20_000


class ConfigurationError(RuntimeError):
    pass


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        if settings.is_deployed and not settings.allow_fake_llm_in_production:
            raise ConfigurationError("fake LLM provider is not allowed in deployed environments")
        return FakeProvider()
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
    attempted: int = 0
    succeeded: int = 0
    cached: int = 0
    failed: Counter[str] = field(default_factory=Counter)
    entities_dropped_ungrounded: int = 0
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

    def as_dict(self) -> dict[str, Any]:
        calls = self.attempted - self.cached
        return {
            "queued": self.queued,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "cached": self.cached,
            "failed": dict(self.failed),
            "failed_total": sum(self.failed.values()),
            "entities_dropped_ungrounded": self.entities_dropped_ungrounded,
            "cost_usd": float(self.cost_usd),
            "spent_today_usd": float(self.spent_today_usd),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "avg_latency_ms": round(self.latency_ms_total / calls) if calls > 0 else None,
            "budget_exhausted": self.budget_exhausted,
            "circuit_open": self.circuit_open,
            "fatal_error": self.fatal_error,
            "skipped_reason": self.skipped_reason,
        }


@dataclass(frozen=True, slots=True)
class QueueItem:
    article_id: int
    attempts: int
    article: ArticleInput
    input_hash: str


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


# ---------------------------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------------------------
def load_queue(
    session: Session, settings: Settings, model: str, article_ids: Iterable[int] | None = None
) -> list[QueueItem]:
    query = (
        select(
            Article.id,
            Article.enrichment_attempts,
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
        query = query.where(
            or_(
                Article.enrichment_status == "pending",
                (Article.enrichment_status == "failed")
                & (Article.enrichment_attempts < settings.enrich_max_attempts),
            )
        )
    query = query.order_by(Article.published_at.desc()).limit(settings.enrich_max_per_run)
    items = []
    for row in session.execute(query):
        art = ArticleInput(
            source_name=row.name, published=row.published_date, title=row.title, excerpt=row.excerpt
        )
        items.append(QueueItem(row.id, row.enrichment_attempts, art, input_hash(art, model)))
    return items


def find_cached(session: Session, ihash: str, model: str, article_id: int) -> Enrichment | None:
    """Reuse another article's result for identical input (syndicated copies).

    An article's *own* earlier results are excluded: re-queueing an article means "analyse it
    again" (e.g. a suspected bad output), which a cache hit would silently turn into a no-op.
    """
    return session.scalar(
        select(Enrichment)
        .where(
            Enrichment.article_id != article_id,
            Enrichment.input_hash == ihash,
            Enrichment.prompt_version == PROMPT_VERSION,
            Enrichment.model == model,
            Enrichment.status.in_(("succeeded", "cached")),
            Enrichment.output.is_not(None),
        )
        .order_by(Enrichment.id.desc())
        .limit(1)
    )


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
    try:
        output, flags = parse_output(result.text)
    except InvalidOutputError as exc:
        outcome.status, outcome.error, outcome.error_kind = "invalid", str(exc)[:1000], "invalid"
        return outcome
    source_text = f"{item.article.title}\n{item.article.excerpt or ''}"
    kept, dropped = ground_entities(output.entities, source_text)
    if dropped:
        flags["entities_ungrounded"] = [e.name for e in dropped]
        output = output.model_copy(update={"entities": kept})
    outcome.output, outcome.flags = output, flags
    return outcome


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
    stmt = (
        insert(Entity)
        .values([{"type": t, "normalized_key": k, "name": n} for (t, k), n in wanted.items()])
        .on_conflict_do_nothing(index_elements=[Entity.type, Entity.normalized_key])
    )
    session.execute(stmt)
    rows = session.execute(
        select(Entity.id, Entity.type, Entity.normalized_key).where(
            Entity.normalized_key.in_([k for _, k in wanted]),
            Entity.type.in_({t for t, _ in wanted}),
        )
    )
    return [r.id for r in rows if (r.type, r.normalized_key) in wanted]


def apply_output(session: Session, article_id: int, output: EnrichmentOutput) -> None:
    """Make ``output`` the article's current analysis (denormalized fields + bridges)."""
    now = datetime.now(UTC)
    published_date = session.execute(
        update(Article)
        .where(Article.id == article_id)
        .values(
            enrichment_status="succeeded",
            enriched_at=now,
            primary_topic_id=TOPIC_BY_SLUG[output.primary_topic].id,
            sentiment_label=output.sentiment,
            sentiment_score=round(output.sentiment_score, 3),
            event_type=output.event_type,
            detected_language=output.language,
            countries=output.countries,
            summary_en=output.summary_en,
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
    cached_from: Enrichment | None = None,
) -> None:
    item = outcome.item
    attempt = item.attempts + 1
    success = outcome.status in ("succeeded", "cached") and outcome.output is not None
    if success:
        session.execute(
            update(Enrichment)
            .where(Enrichment.article_id == item.article_id, Enrichment.is_current.is_(True))
            .values(is_current=False)
        )
    session.add(
        Enrichment(
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
    )
    if success:
        assert outcome.output is not None
        apply_output(session, item.article_id, outcome.output)
        session.execute(
            update(Article).where(Article.id == item.article_id).values(enrichment_attempts=attempt)
        )
    elif outcome.fatal:
        # Configuration problem (bad key, unknown model): not the article's fault — leave it
        # queued without consuming one of its attempts.
        return
    else:
        # refused → never retry; otherwise retry until attempts are exhausted
        terminal = outcome.status == "refused"
        session.execute(
            update(Article)
            .where(Article.id == item.article_id)
            .values(
                enrichment_attempts=attempt, enrichment_status="skipped" if terminal else "failed"
            )
        )
        if attempt >= max_attempts and not terminal:
            log.warning(
                "article exhausted enrichment attempts",
                extra={"article_id": item.article_id, "error": outcome.error},
            )


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
) -> EnrichStats:
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
        queue = load_queue(session, settings, provider.model, article_ids)
        stats.spent_today_usd = spent_today(session)
    stats.queued = len(queue)
    if not queue:
        return stats

    budget = BudgetGuard(
        settings.llm_daily_budget_usd, stats.spent_today_usd, on_exhausted=on_budget_exhausted
    )
    consecutive_failures = 0
    pending: dict[Future[CallOutcome], QueueItem] = {}
    queue_iter = iter(queue)
    stop_dispatch = False

    def record(outcome: CallOutcome, cached_from: Enrichment | None = None) -> None:
        nonlocal consecutive_failures
        with session_factory() as s, s.begin():
            persist_outcome(
                s,
                outcome,
                run_id=run_id,
                provider_name=provider.name,
                max_attempts=settings.enrich_max_attempts,
                cached_from=cached_from,
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
            consecutive_failures = 0
        else:
            stats.failed[outcome.error_kind or outcome.status] += 1
            if outcome.status != "refused":
                consecutive_failures += 1

    with ThreadPoolExecutor(
        max_workers=settings.enrich_concurrency, thread_name_prefix="enrich"
    ) as pool:
        while True:
            # Fill the worker pool.
            while not stop_dispatch and len(pending) < settings.enrich_concurrency:
                item = next(queue_iter, None)
                if item is None:
                    stop_dispatch = True
                    break
                with session_factory() as s:
                    cached = find_cached(s, item.input_hash, provider.model, item.article_id)
                if cached is not None and cached.output is not None:
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
                pending[pool.submit(call_llm, provider, item, estimate)] = item
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                pending.pop(fut)
                outcome = fut.result()
                budget.settle(outcome.estimate, outcome.cost)
                record(outcome)
                if outcome.fatal and not stats.fatal_error:
                    stats.fatal_error = outcome.error
                    stop_dispatch = True
                    log.error(
                        "fatal LLM error — stopping enrichment", extra={"error": outcome.error}
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
