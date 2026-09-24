from __future__ import annotations

import httpx
import pytest

from gjurme.alerts.engine import Alert, _format_payload, evaluate_run
from gjurme.config import ConfigError, Settings


def _keys(alerts: list[Alert]) -> set[str]:
    return {a.key.split(":")[0] for a in alerts}


class TestAlertRules:
    def test_healthy_run_has_no_alerts(self) -> None:
        stats = {
            "ingest": {"sources_total": 3, "sources_ok": 3, "auto_disabled": []},
            "enrich": {"budget_exhausted": False},
            "quality": {"results": []},
        }
        assert evaluate_run("succeeded", stats) == []

    def test_failed_run(self) -> None:
        assert "pipeline_failed" in _keys(evaluate_run("failed", {"error": "db down"}))

    def test_all_sources_down(self) -> None:
        stats = {
            "ingest": {
                "sources_total": 2,
                "sources_ok": 0,
                "per_source": [
                    {"slug": "a", "status": "timeout", "error": "x"},
                    {"slug": "b", "status": "http_error", "error": "y"},
                ],
            }
        }
        alerts = evaluate_run("partial", stats)
        assert "all_sources_down" in _keys(alerts)
        assert alerts[0].severity == "critical"

    def test_auto_disabled_budget_circuit_dq(self) -> None:
        stats = {
            "ingest": {"sources_total": 2, "sources_ok": 1, "auto_disabled": ["koha"]},
            "enrich": {"budget_exhausted": True, "spent_today_usd": 2.0, "circuit_open": True},
            "quality": {
                "results": [
                    {
                        "name": "enrichment_consistency",
                        "status": "fail",
                        "observed": 3,
                        "threshold": 0,
                        "details": {},
                    },
                    {
                        "name": "article_volume_anomaly",
                        "status": "warn",
                        "observed": 4.2,
                        "threshold": 3,
                        "details": {},
                    },
                    {
                        "name": "duplicate_rate_24h",
                        "status": "warn",
                        "observed": 0.97,
                        "threshold": 0.95,
                        "details": {},
                    },
                ]
            },
        }
        keys = {a.key for a in evaluate_run("partial", stats)}
        assert "source_auto_disabled:koha" in keys
        assert any(k.startswith("llm_budget_exhausted:") for k in keys)
        assert "llm_circuit_open" in keys
        assert "dq:enrichment_consistency" in keys
        assert "dq:article_volume_anomaly" in keys
        assert "dq:duplicate_rate_24h" not in keys  # warnings are not paged

    def test_fatal_error_supersedes_circuit(self) -> None:
        keys = _keys(
            evaluate_run(
                "partial", {"enrich": {"fatal_error": "auth: bad key", "circuit_open": True}}
            )
        )
        assert "llm_fatal_error" in keys and "llm_circuit_open" not in keys

    @pytest.mark.parametrize("fmt", ["slack", "discord", "ntfy", "generic"])
    def test_payload_formats(self, fmt: str) -> None:
        body, headers = _format_payload(fmt, Alert("k", "critical", "T", "M"), "production")
        if fmt == "ntfy":
            assert body == "M" and headers["Priority"] == "high"
        elif fmt == "generic":
            assert isinstance(body, dict) and body["key"] == "k"
        else:
            assert "production" in str(body)


class TestConfig:
    def _prod(self, **kw: object) -> Settings:
        base = {
            "gjurme_env": "production",
            "database_url": "postgresql+psycopg://app:s3cret@db/gjurme",
            "admin_api_token": "x" * 40,
            "cors_origins": "https://gjurme.example",
        }
        return Settings(_env_file=None, **{**base, **kw})  # type: ignore[arg-type]

    def test_valid_production_config(self) -> None:
        self._prod().validate_for_env()

    @pytest.mark.parametrize(
        ("override", "fragment"),
        [
            ({"admin_api_token": "short"}, "ADMIN_API_TOKEN"),
            ({"admin_api_token": None}, "ADMIN_API_TOKEN"),
            ({"cors_origins": "*"}, "CORS_ORIGINS"),
            ({"llm_provider": "fake"}, "LLM_PROVIDER"),
            ({"database_url": "postgresql+psycopg://gjurme:gjurme@db/gjurme"}, "DATABASE_URL"),
        ],
    )
    def test_unsafe_production_config_rejected(
        self, override: dict[str, object], fragment: str
    ) -> None:
        with pytest.raises(ConfigError, match=fragment):
            self._prod(**override).validate_for_env()

    def test_development_is_permissive(self) -> None:
        Settings(_env_file=None, gjurme_env="development", cors_origins="*").validate_for_env()  # type: ignore[call-arg]

    def test_cors_origins_comma_separated(self) -> None:
        s = Settings(_env_file=None, cors_origins="https://a.example, https://b.example")  # type: ignore[call-arg]
        assert s.cors_origins == ["https://a.example", "https://b.example"]


def test_dispatch_formats_are_json_serializable() -> None:
    body, _ = _format_payload("generic", Alert("k", "info", "T", "M", {"n": 1}), "dev")
    httpx.Request("POST", "https://hooks.example.com", json=body)
