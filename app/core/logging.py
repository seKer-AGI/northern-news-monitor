"""Structured logging with secret redaction.

Use ``logger.info("message", extra={"source_id": 1})``; extra fields are
emitted as JSON keys (or ``key=value`` pairs in text mode).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

# Generic patterns that must never reach a log sink, whatever their value.
_PATTERNS = [
    (re.compile(r"(access_token=)[^&\s\"']+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(appsecret_proof=)[^&\s\"']+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(client_secret=)[^&\s\"']+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.I), r"\1[REDACTED]"),
]


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self.secrets = [s for s in (secrets or []) if len(s) >= 4]

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        for pattern, repl in _PATTERNS:
            text = pattern.sub(repl, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = None
        for key, value in list(vars(record).items()):
            if key not in _RESERVED and isinstance(value, str):
                setattr(record, key, self.redact(value))
        return True


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in vars(record).items() if k not in _RESERVED}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_extras(record),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%d %H:%M:%S")
        extras = " ".join(f"{k}={v}" for k, v in _extras(record).items())
        line = f"{ts} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if extras:
            line = f"{line} | {extras}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(
    level: str = "INFO", fmt: str = "json", secrets: list[str] | None = None
) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(RedactingFilter(secrets))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # httpx logs full request URLs at INFO; Graph API URLs carry access tokens.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for uv in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(uv).handlers = []
        logging.getLogger(uv).propagate = True
