"""Structured logging.

JSON lines on stdout (container-friendly: Docker/journald collect them, `jq` reads them).
A ``run_id`` context variable is attached to every record emitted during a pipeline run so that
all log lines of one run can be correlated with ``ops.pipeline_runs``.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

run_id_var: ContextVar[int | None] = ContextVar("run_id", default=None)
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        run_id = run_id_var.get()
        if run_id is not None:
            payload["run_id"] = run_id
        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")
        }
        run_id = run_id_var.get()
        if run_id is not None:
            extras["run_id"] = run_id
        if extras:
            base += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return base


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Third-party noise: keep warnings, drop per-request chatter.
    for noisy in ("httpx", "httpcore", "anthropic", "urllib3", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # uvicorn installs its own plain-text handlers; route its records through the JSON handler
    # instead so every line in the container log is structured. Requests are logged by the app.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers[:] = []
        uv_logger.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
