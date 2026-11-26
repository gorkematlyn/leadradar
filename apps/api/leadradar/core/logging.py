"""Structured JSON logging. Tokens and secrets must never be passed to loggers."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

_REDACT = re.compile(r"(/r/)[A-Za-z0-9_\-]{8,}|(token=)[^&\s]+|(lr_session=)[^;\s]+", re.IGNORECASE)


def redact(text: str) -> str:
    return _REDACT.sub(lambda m: (m.group(1) or m.group(2) or m.group(3)) + "[redacted]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "data", None)
        if isinstance(extra, dict):
            payload["data"] = extra
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # uvicorn access logs include request paths (public report tokens); replace with our middleware log.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
