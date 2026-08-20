"""Structured JSON logging with secret redaction and correlation IDs.

Two rules this module enforces mechanically:

* No key, cookie, or token ever reaches a log record (RULES.md §4).
* Every record carries the correlation IDs needed to reconstruct one request
  across the API and the worker.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from typing import Any

from src.core.config import SECRET_FIELDS, get_settings

#: Correlation identifiers, propagated per request/job via context vars.
_CORRELATION: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "correlation", default=None
)

CORRELATION_KEYS = ("trace_id", "session_id", "conversation_id", "job_id", "index_version")

_REDACTED = "[REDACTED]"

#: Key names whose values are always redacted, regardless of nesting.
_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|auth|password|passwd|secret|token|cookie|set-cookie"
    r"|session[_-]?id_value|database_url|redis_url|dsn)",
    re.IGNORECASE,
)

#: Value shapes that are secrets wherever they appear in free text.
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\b(?:sk|aa|pk)-[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:@/]+:[^\s@/]+@", re.IGNORECASE),
)


def set_correlation(**values: str | None) -> None:
    """Merge correlation identifiers into the current context."""
    current = dict(_CORRELATION.get() or {})
    for key, value in values.items():
        if value is None:
            continue
        if key not in CORRELATION_KEYS:
            raise ValueError(f"unknown correlation key: {key}")
        current[key] = str(value)
    _CORRELATION.set(current)


def get_correlation() -> dict[str, str]:
    return dict(_CORRELATION.get() or {})


def clear_correlation() -> None:
    _CORRELATION.set(None)


def redact_text(text: str) -> str:
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact secrets from anything destined for a log record."""
    if _depth > 8:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _SENSITIVE_KEY_RE.search(key_str) or key_str in SECRET_FIELDS:
                out[key_str] = _REDACTED
            else:
                out[key_str] = redact(item, _depth=_depth + 1)
        return out
    if isinstance(value, list | tuple | set):
        return [redact(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        payload.update(get_correlation())

        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            payload.update(redact(extras))

        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str | None = None) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel((level or get_settings().log_level).upper())

    # uvicorn installs its own colourised handlers; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
