"""Daily LLM spend guard.

Spend is the sum of ``core.enrichments.cost_usd`` since 00:00 UTC — the database is the source of
truth, so the limit holds across restarts, concurrent processes and manual CLI runs. Within one
run, calls *reserve* a pessimistic estimate before being sent and *settle* the actual cost after,
so concurrent workers cannot collectively overshoot the budget.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gjurme.db.models import Enrichment


def utc_day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return datetime.combine(now.date(), time.min, tzinfo=UTC)


def spent_today(session: Session, now: datetime | None = None) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(Enrichment.cost_usd), 0)).where(
            Enrichment.created_at >= utc_day_start(now)
        )
    )
    return Decimal(total or 0)


class BudgetGuard:
    def __init__(
        self,
        daily_budget_usd: float,
        spent_at_start: Decimal,
        on_exhausted: Callable[[], None] | None = None,
    ) -> None:
        self.budget = Decimal(str(daily_budget_usd))
        self._spent = spent_at_start
        self._reserved = Decimal(0)
        self._lock = threading.Lock()
        self.exhausted = False
        self._on_exhausted = on_exhausted

    @property
    def spent(self) -> Decimal:
        return self._spent

    @property
    def remaining(self) -> Decimal:
        return max(Decimal(0), self.budget - self._spent - self._reserved)

    def try_reserve(self, estimate: Decimal) -> bool:
        with self._lock:
            if self._spent + self._reserved + estimate > self.budget:
                if not self.exhausted:
                    self.exhausted = True
                    if self._on_exhausted:
                        self._on_exhausted()
                return False
            self._reserved += estimate
            return True

    def settle(self, estimate: Decimal, actual: Decimal) -> None:
        with self._lock:
            self._reserved -= estimate
            self._spent += actual
