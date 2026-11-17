"""A free tier's daily request quota, spread over the day.

Gemini's free tier allows a few hundred requests a day and resets at midnight Pacific time.
Sent as fast as the queue allows, the quota was gone by 19:00 UTC and the evening's and the
night's news got the keyword rules. Each run now gets a share instead::

    share = ⌈(daily limit − requests since the reset) / runs left until the reset⌉   (≥ 1)

with the runs ``SCHEDULER_INTERVAL_MINUTES`` apart, and ``LLM_MAX_REQUESTS_PER_RUN`` as a fixed
ceiling besides. A run that starts late, or a run that is skipped, leaves its share to the runs
after it. The last run before the reset may use whatever is left: unused quota is lost at
midnight. Within a run the queue is newest first, so the newest articles get the model.

The daily limit is not a fixed number. ``LLM_REQUESTS_PER_DAY`` is where it starts (0 =
unknown, no pacing); after that the provider's answers decide, per model, in ``ops.llm_quota``:

* a 429 for the day (or one that does not say which limit it is) marks the model *limited*:
  the run stops, the next runs send a single request first, and only when that one is answered
  do they go on. If the day ends still limited, the requests answered before the 429 are the
  daily limit from then on;
* a day that ended with more requests than the limit and no 429 (the last run of the day uses
  what is left, and every run sends at least one request) raises the limit to that many;
* a 429 per minute is the provider's pacing, not the day's quota: it changes nothing here;
* a new ``LLM_REQUESTS_PER_DAY`` replaces what was learned.

Requests are counted when the provider answered them: a 429 or a failed connection costs no
quota, a request whose answer could not be used does. The counts are the database's, so the
pacing holds across runs, processes and manual CLI runs (the row is locked while it is read).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gjurme.config import Settings
from gjurme.db.models import LLMQuota


@dataclass(frozen=True, slots=True)
class QuotaConfig:
    """One model's quota settings (LLM_* for the first model, LLM_FALLBACK_* for the second)."""

    requests_per_day: int = 0  # 0 = unknown until the first 429 for the day
    max_requests_per_run: int = 0  # 0 = no fixed ceiling
    timezone: str = "UTC"  # where the provider's day starts
    interval_minutes: int = 30  # between runs

    @classmethod
    def for_model(cls, settings: Settings, *, fallback: bool = False) -> QuotaConfig:
        if fallback:
            return cls(
                settings.llm_fallback_requests_per_day,
                settings.llm_fallback_max_requests_per_run,
                settings.llm_fallback_quota_timezone,
                settings.scheduler_interval_minutes,
            )
        return cls(
            settings.llm_requests_per_day,
            settings.llm_max_requests_per_run,
            settings.llm_quota_timezone,
            settings.scheduler_interval_minutes,
        )


@dataclass(frozen=True, slots=True)
class QuotaPlan:
    """What one run may send to one model."""

    model: str
    quota_day: date
    resets_at: datetime
    used: int  # requests answered since the reset, before this run
    daily_limit: int | None  # None = unknown: no pacing
    limit_source: Literal["configured", "learned"] | None
    limited: bool  # a 429 for the day since the reset that no answer has cleared
    runs_left: int  # this one included
    cap: int | None  # requests for this run; None = no limit but the queue and the time

    def as_dict(self) -> dict[str, Any]:
        return {
            "quota_day": self.quota_day.isoformat(),
            "resets_at": self.resets_at.isoformat(),
            "used_before_run": self.used,
            "daily_limit": self.daily_limit,
            "limit_source": self.limit_source,
            "limited": self.limited,
            "runs_left": self.runs_left,
            "cap": self.cap,
        }


def quota_day(now: datetime, timezone: str) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


def next_reset(day: date, timezone: str) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=ZoneInfo(timezone))


def runs_left(now: datetime, resets_at: datetime, interval_minutes: int) -> int:
    """Runs until the reset, this one included: one every ``interval_minutes``."""
    seconds = (resets_at - now).total_seconds()
    return max(1, math.ceil(seconds / (interval_minutes * 60)))


def run_share(
    *, used: int, daily_limit: int | None, runs_left: int, max_per_run: int = 0
) -> int | None:
    """Requests one run may send: an even share of what is left of the day, at least one so a
    raised limit shows and the newest article still gets a model; everything that is left in
    the last run before the reset. ``max_per_run`` caps it either way (0 = no cap)."""
    share: int | None = None
    if daily_limit is not None and runs_left > 1:
        share = max(1, math.ceil(max(daily_limit - used, 0) / runs_left))
    if max_per_run:
        share = max_per_run if share is None else min(share, max_per_run)
    return share


def _estimate(row: LLMQuota) -> tuple[int | None, Literal["configured", "learned"] | None]:
    if row.learned_limit is not None:
        return row.learned_limit, "learned"
    if row.configured_limit:
        return row.configured_limit, "configured"
    return None, None


def _roll_over(row: LLMQuota, day: date, configured: int) -> None:
    """Start the model's new quota day, learning from the one that ended."""
    if row.quota_day != day:
        if row.limited_at is not None and row.limited_requests is not None:
            # the day ended at its limit: that is how many requests a day the model allows
            row.learned_limit = row.limited_requests
        else:
            limit, _ = _estimate(row)
            if limit is not None and row.requests > limit:
                row.learned_limit = row.requests  # more were answered than thought possible
        row.quota_day = day
        row.requests = 0
        row.limited_at = None
        row.limited_requests = None
    if row.configured_limit != configured:
        # the operator gave a new figure: it replaces what the 429s taught
        row.configured_limit = configured
        row.learned_limit = None


def begin_run(session: Session, model: str, config: QuotaConfig, now: datetime) -> QuotaPlan:
    """The model's share for a run starting ``now`` (rolls its row over to the current day)."""
    day = quota_day(now, config.timezone)
    session.execute(
        insert(LLMQuota)
        .values(
            model=model,
            quota_day=day,
            requests=0,
            configured_limit=config.requests_per_day,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[LLMQuota.model])
    )
    row = session.execute(
        select(LLMQuota).where(LLMQuota.model == model).with_for_update()
    ).scalar_one()
    _roll_over(row, day, config.requests_per_day)
    row.updated_at = now
    session.flush()
    limit, source = _estimate(row)
    resets_at = next_reset(day, config.timezone)
    left = runs_left(now, resets_at, config.interval_minutes)
    return QuotaPlan(
        model=model,
        quota_day=day,
        resets_at=resets_at,
        used=row.requests,
        daily_limit=limit,
        limit_source=source,
        limited=row.limited_at is not None,
        runs_left=left,
        cap=run_share(
            used=row.requests,
            daily_limit=limit,
            runs_left=left,
            max_per_run=config.max_requests_per_run,
        ),
    )


def note(
    session: Session,
    model: str,
    now: datetime,
    *,
    requests: int = 0,
    limited: bool = False,
    cleared: bool = False,
) -> None:
    """Count answered requests; mark a 429 for the day (``limited``, once until cleared), or
    clear it when a request sent after it was answered (``cleared``)."""
    if requests or cleared:
        values: dict[str, Any] = {"requests": LLMQuota.requests + requests, "updated_at": now}
        if cleared:
            values |= {"limited_at": None, "limited_requests": None}
        session.execute(update(LLMQuota).where(LLMQuota.model == model).values(**values))
    if limited:
        session.execute(
            update(LLMQuota)
            .where(LLMQuota.model == model, LLMQuota.limited_at.is_(None))
            .values(limited_at=now, limited_requests=LLMQuota.requests, updated_at=now)
        )
