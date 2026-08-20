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


class RedactingTelemetryHandler(logging.Handler):
    """Forward only the already-redacted JSON representation to OTLP.

    The OpenTelemetry logging handler normally serializes the original record,
    including arbitrary extras. Wrapping it here preserves the same redaction
    guarantee as stdout and avoids recursively exporting exporter diagnostics.
    """

    def __init__(self, delegate: logging.Handler) -> None:
        super().__init__()
        self._delegate = delegate
        self._json = JsonFormatter()

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith(("src", "uvicorn")):
            return
        clean = logging.LogRecord(
            name=record.name,
            level=record.levelno,
            pathname=record.pathname,
            lineno=record.lineno,
            msg=self._json.format(record),
            args=(),
            exc_info=None,
        )
        self._delegate.emit(clean)


_OTEL_PROVIDER: Any | None = None
_OTEL_HANDLER: RedactingTelemetryHandler | None = None


def _telemetry_handler() -> RedactingTelemetryHandler | None:
    global _OTEL_HANDLER, _OTEL_PROVIDER

    settings = get_settings()
    if not settings.otel_logs_enabled or not settings.otel_exporter_otlp_logs_endpoint:
        return None
    if _OTEL_HANDLER is not None:
        return _OTEL_HANDLER

    try:
        # Imports stay lazy: local development does not start exporter threads
        # when telemetry is disabled.
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource

        provider = LoggerProvider(
            resource=Resource.create({"service.name": settings.otel_service_name})
        )
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(
                    endpoint=settings.otel_exporter_otlp_logs_endpoint,
                    timeout=2,
                ),
                schedule_delay_millis=1000,
                export_timeout_millis=2000,
                max_export_batch_size=512,
            )
        )
        set_logger_provider(provider)
        _OTEL_PROVIDER = provider
        _OTEL_HANDLER = RedactingTelemetryHandler(
            LoggingHandler(level=logging.NOTSET, logger_provider=provider)
        )
    except Exception as err:
        # Logging has already been configured for stdout. Observability setup
        # is best effort and must not keep the application from starting.
        logging.getLogger(__name__).warning(
            "OTLP logging disabled after setup failure",
            extra={"cause": str(err)},
        )
        return None
    return _OTEL_HANDLER


def configure_logging(level: str | None = None) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    telemetry_handler = _telemetry_handler()
    if telemetry_handler is not None:
        root.addHandler(telemetry_handler)
    root.setLevel((level or get_settings().log_level).upper())

    # uvicorn installs its own colourised handlers; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def shutdown_telemetry_logging() -> None:
    """Flush the best-effort OTLP queue without affecting process shutdown."""
    global _OTEL_HANDLER, _OTEL_PROVIDER

    provider = _OTEL_PROVIDER
    _OTEL_HANDLER = None
    _OTEL_PROVIDER = None
    if provider is None:
        return
    try:
        provider.shutdown()
    except Exception:  # telemetry failure must never block shutdown
        logging.getLogger(__name__).warning("telemetry logger shutdown failed")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
