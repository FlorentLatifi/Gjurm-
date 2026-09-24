"""Prometheus metrics.

* HTTP metrics are recorded by middleware (per route template, so cardinality stays bounded).
* Pipeline / LLM / source metrics are *computed from the database at scrape time* by a custom
  collector (cached 30 s). The scheduler process therefore needs no metrics endpoint or push
  gateway: the database is already the source of truth for runs, costs and source health.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


class PipelineCollector(Collector):
    def __init__(
        self, session_factory: Callable[[], Session], daily_budget: float, ttl: float = 30.0
    ) -> None:
        self._factory = session_factory
        self._budget = daily_budget
        self._ttl = ttl
        self._cache: tuple[float, list[GaugeMetricFamily]] | None = None

    def collect(self) -> Iterator[GaugeMetricFamily]:
        now = time.monotonic()
        if self._cache and self._cache[0] > now:
            yield from self._cache[1]
            return
        try:
            families = self._families()
        except Exception:
            log.exception("metrics collection failed")
            up = GaugeMetricFamily("gjurme_metrics_db_up", "Database reachable for metrics")
            up.add_metric([], 0)
            yield up
            return
        self._cache = (now + self._ttl, families)
        yield from families

    def _families(self) -> list[GaugeMetricFamily]:
        with self._factory() as s:

            def q(sql: str) -> Any:
                return s.execute(text(sql)).one()._mapping

            runs = q("""
                SELECT extract(epoch FROM max(finished_at) FILTER (
                           WHERE status IN ('succeeded', 'partial'))) AS last_success,
                       (SELECT status FROM ops.pipeline_runs
                        WHERE status NOT IN ('skipped_locked') ORDER BY started_at DESC LIMIT 1)
                         AS last_status,
                       count(*) FILTER (WHERE status = 'failed'
                                        AND started_at > now() - interval '24 hours') AS failed_24h
                FROM ops.pipeline_runs""")
            arts = q("""
                SELECT count(*) FILTER (WHERE ingested_at > now() - interval '24 hours') AS new_24h,
                       count(*) FILTER (WHERE enrichment_status IN ('pending', 'failed')
                                        AND NOT is_hidden) AS backlog
                FROM core.articles""")
            llm = q("""
                SELECT coalesce(sum(cost_usd) FILTER (WHERE created_at >= date_trunc('day', now())),
                                0) AS cost_today,
                       count(*) FILTER (WHERE status IN ('failed', 'invalid', 'refused')
                                        AND created_at > now() - interval '24 hours') AS failed_24h,
                       count(*) FILTER (WHERE status <> 'cached'
                                        AND created_at > now() - interval '24 hours') AS calls_24h,
                       avg(latency_ms) FILTER (WHERE status <> 'cached'
                                               AND created_at > now() - interval '24 hours')
                         AS latency_ms
                FROM core.enrichments""")
            sources = s.execute(
                text("SELECT slug, is_active, consecutive_failures FROM core.sources")
            ).all()

        def gauge(
            name: str, doc: str, value: Any, labels: dict[str, str] | None = None
        ) -> GaugeMetricFamily:
            g = GaugeMetricFamily(name, doc, labels=list(labels or {}))
            g.add_metric(list((labels or {}).values()), float(value or 0))
            return g

        fams = [
            gauge("gjurme_metrics_db_up", "Database reachable for metrics", 1),
            gauge(
                "gjurme_pipeline_last_success_timestamp_seconds",
                "Unix time of the last successful/partial pipeline run",
                runs["last_success"],
            ),
            gauge(
                "gjurme_pipeline_failed_runs_24h",
                "Failed runs in the last 24 h",
                runs["failed_24h"],
            ),
            gauge(
                "gjurme_articles_ingested_24h",
                "Articles ingested in the last 24 h",
                arts["new_24h"],
            ),
            gauge("gjurme_enrichment_backlog", "Articles waiting for enrichment", arts["backlog"]),
            gauge("gjurme_llm_cost_today_usd", "LLM spend since 00:00 UTC", llm["cost_today"]),
            gauge("gjurme_llm_daily_budget_usd", "Configured daily LLM budget", self._budget),
            gauge("gjurme_llm_calls_24h", "LLM calls in the last 24 h", llm["calls_24h"]),
            gauge(
                "gjurme_llm_failures_24h", "Failed LLM attempts in the last 24 h", llm["failed_24h"]
            ),
            gauge(
                "gjurme_llm_latency_ms_avg_24h",
                "Mean LLM latency (ms), last 24 h",
                llm["latency_ms"],
            ),
        ]
        status = GaugeMetricFamily(
            "gjurme_pipeline_last_run_status",
            "1 for the status of the most recent run",
            labels=["status"],
        )
        for st in ("succeeded", "partial", "failed", "running", "abandoned"):
            status.add_metric([st], 1.0 if runs["last_status"] == st else 0.0)
        up = GaugeMetricFamily("gjurme_source_active", "Source is active", labels=["source"])
        fails = GaugeMetricFamily(
            "gjurme_source_consecutive_failures", "Consecutive fetch failures", labels=["source"]
        )
        for slug, active, failures in sources:
            up.add_metric([slug], 1.0 if active else 0.0)
            fails.add_metric([slug], float(failures))
        return [*fams, status, up, fails]


class ApiMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.requests = Counter(
            "gjurme_http_requests_total",
            "HTTP requests",
            ["method", "route", "status"],
            registry=registry,
        )
        self.latency = Histogram(
            "gjurme_http_request_duration_seconds",
            "HTTP latency",
            ["route"],
            registry=registry,
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
        )
        self.rate_limited = Counter(
            "gjurme_http_rate_limited_total",
            "Requests rejected (429)",
            ["bucket"],
            registry=registry,
        )
