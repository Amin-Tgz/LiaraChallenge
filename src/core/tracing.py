"""Opik spans for retrieval, generation, and the bounded agent loop.

Not to be confused with `_Tracer` in `src/services/agent.py`: that relays
ThinkingTrace steps to the browser over SSE and is part of the product. Nothing
in this module is user-visible — it ships operator telemetry to Opik.

Three properties this module holds, in order of importance:

* **A telemetry failure never fails a user request.** Every entry point is
  wrapped; the first setup failure disables tracing for the process and logs a
  warning, exactly as `_telemetry_handler` does for OTLP logs.
* **Imports stay lazy.** With `OPIK_ENABLED=false` the `opik` package is never
  imported, so no client, queue, or background thread is created.
* **No credential reaches a span.** Input, output, and metadata pass through
  the same `redact()` used for log records before leaving the process. Token
  counts are exempt and explained at that call site.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from src.core.config import Settings, get_settings
from src.core.logging import get_logger, redact

logger = get_logger(__name__)

SpanKind = Literal["general", "tool", "llm", "guardrail"]

#: The innermost open span, so a child links to its parent without any call
#: site having to pass a handle down. `contextvars` propagates into
#: `asyncio.to_thread`, which is how the synchronous embedding client stays
#: attached to the agent turn that triggered it.
_CURRENT: contextvars.ContextVar[_Node | None] = contextvars.ContextVar(
    "opik_current_span", default=None
)

_LOCK = threading.Lock()
_CLIENT: Any | None = None
#: Set after any failure. Tracing is attempted once per process, not once per
#: request: a telemetry backend that is down must not cost every caller a
#: connection attempt.
_UNAVAILABLE = False


@dataclass(slots=True)
class _Node:
    """The open trace and span a child should attach to."""

    trace: Any
    span: Any


def _disable(reason: str, err: BaseException | None = None) -> None:
    global _UNAVAILABLE, _CLIENT
    if _UNAVAILABLE:
        return
    _UNAVAILABLE = True
    _CLIENT = None
    logger.warning(
        "Opik tracing disabled after failure",
        extra={"reason": reason, "cause": type(err).__name__ if err else None},
    )


def tracing_enabled(settings: Settings | None = None) -> bool:
    """Whether configuration asks for tracing — not whether it is working."""
    settings = settings or get_settings()
    return bool(settings.opik_enabled and settings.opik_api_key and settings.opik_workspace)


def configure_tracing(settings: Settings | None = None) -> bool:
    """Build the Opik client once, at startup, off the request path.

    Returns whether tracing is live. Safe to call more than once, and safe to
    call when Opik is unreachable — the failure is logged, not raised.
    """
    global _CLIENT

    settings = settings or get_settings()
    if not tracing_enabled(settings):
        return False
    if _UNAVAILABLE:
        return False
    if _CLIENT is not None:
        return True

    with _LOCK:
        if _CLIENT is not None:
            return True
        try:
            # Lazy: nothing above imports opik, so a disabled deployment never
            # loads the SDK or starts its sender thread.
            import opik

            _CLIENT = opik.Opik(
                project_name=settings.opik_project_name,
                workspace=settings.opik_workspace,
                host=settings.opik_url_override or None,
                api_key=settings.opik_api_key,
                _show_misconfiguration_message=False,
            )
        except Exception as err:  # noqa: BLE001 - telemetry setup is best effort
            _disable("client construction failed", err)
            return False
    logger.info(
        "Opik tracing enabled",
        extra={
            "project": settings.opik_project_name,
            "capture_content": settings.opik_capture_content,
        },
    )
    return True


def shutdown_tracing() -> None:
    """Flush queued spans without letting a stuck exporter block shutdown."""
    global _CLIENT

    client = _CLIENT
    _CLIENT = None
    if client is None:
        return
    try:
        client.flush(timeout=int(get_settings().opik_flush_timeout_seconds))
    except Exception:  # noqa: BLE001 - a failed flush must not block shutdown
        logger.warning("Opik span flush failed")


def reset_tracing_for_tests() -> None:
    """Drop cached client state. Test-only; production configures once."""
    global _CLIENT, _UNAVAILABLE

    _CLIENT = None
    _UNAVAILABLE = False
    _CURRENT.set(None)


@dataclass(slots=True)
class SpanRecorder:
    """Accumulates what a span should report. Every method is a no-op when off.

    Values are collected rather than pushed so that one `redact()` pass covers
    the whole payload at close, and so a caller can record fields before it
    knows whether the operation will succeed.
    """

    _live: bool = False
    _capture_content: bool = False
    _input: dict[str, Any] = field(default_factory=dict)
    _output: dict[str, Any] = field(default_factory=dict)
    _metadata: dict[str, Any] = field(default_factory=dict)
    _usage: dict[str, Any] = field(default_factory=dict)
    _model: str | None = None
    _provider: str | None = None
    _error: dict[str, str] | None = None

    @property
    def captures_content(self) -> bool:
        """Whether prompt and answer text is being sent to the backend."""
        return self._live and self._capture_content

    def metadata(self, **fields: Any) -> None:
        """Record non-content facts: counts, similarities, models, codes."""
        if self._live:
            self._metadata.update(fields)

    def output(self, **fields: Any) -> None:
        if self._live:
            self._output.update(fields)

    def content(self, **fields: Any) -> None:
        """Record user or documentation text, subject to OPIK_CAPTURE_CONTENT."""
        if self.captures_content:
            self._input.update(fields)

    def content_output(self, **fields: Any) -> None:
        if self.captures_content:
            self._output.update(fields)

    def usage(
        self,
        *,
        model: str | None = None,
        provider: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        if not self._live:
            return
        if model is not None:
            self._model = model
        if provider is not None:
            self._provider = provider
        for key, value in (
            ("prompt_tokens", prompt_tokens),
            ("completion_tokens", completion_tokens),
            ("total_tokens", total_tokens),
        ):
            if value is not None:
                self._usage[key] = int(value)

    def error(self, code: str, detail: str | None = None) -> None:
        """Attach a failure cause using the taxonomy code, never a stack trace."""
        if self._live:
            self._error = {"exception_type": code, "message": detail or code}

    def _payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in (
            ("input", self._input),
            ("output", self._output),
            ("metadata", self._metadata),
        ):
            if value:
                payload[key] = redact(dict(value))
        if self._usage:
            # Deliberately not redacted. The log redactor matches any key
            # containing "token", which would blank `prompt_tokens` and
            # `total_tokens` — and these are integers this module coerced
            # itself, so there is nothing here for it to protect.
            payload["usage"] = dict(self._usage)
        if self._model is not None:
            payload["model"] = self._model
        if self._provider is not None:
            payload["provider"] = self._provider
        if self._error is not None:
            payload["error_info"] = redact(dict(self._error))
        return payload


#: Shared instance for the disabled path; it holds no state and mutates nothing.
_OFF = SpanRecorder()


@contextlib.contextmanager
def opik_span(
    name: str,
    *,
    kind: SpanKind = "general",
    root: bool = False,
    thread_id: str | None = None,
    tags: Mapping[str, Any] | None = None,
) -> Iterator[SpanRecorder]:
    """Open one span, nested under whichever span is currently open.

    `root=True` starts a new trace even inside an open span — used for a job,
    so one agent turn is one trace rather than a child of whatever ran it.
    `thread_id` groups traces of the same conversation on the Opik side.
    """
    settings = get_settings()
    if not configure_tracing(settings):
        yield _OFF
        return

    client = _CLIENT
    if client is None:  # disabled between the check and here
        yield _OFF
        return

    parent = _CURRENT.get()
    try:
        if parent is None or root:
            trace = client.trace(name=name, thread_id=thread_id)
            span = trace.span(name=name, type=kind)
        else:
            trace = parent.trace
            span = parent.span.span(name=name, type=kind)
    except Exception as err:  # noqa: BLE001 - never fail the caller
        _disable("span creation failed", err)
        yield _OFF
        return

    recorder = SpanRecorder(_live=True, _capture_content=settings.opik_capture_content)
    if tags:
        recorder.metadata(**dict(tags))
    owns_trace = parent is None or root
    token = _CURRENT.set(_Node(trace=trace, span=span))
    try:
        yield recorder
    except BaseException as exc:
        recorder.error(type(exc).__name__, getattr(exc, "detail", None) or str(exc))
        _close(span, trace if owns_trace else None, recorder)
        raise
    else:
        _close(span, trace if owns_trace else None, recorder)
    finally:
        _CURRENT.reset(token)


def opik_turn(
    name: str,
    *,
    kind: SpanKind = "general",
    thread_id: str | None = None,
    tags: Mapping[str, Any] | None = None,
) -> contextlib.AbstractContextManager[SpanRecorder]:
    """Start a trace of its own: one job, one trace, with children beneath it."""
    return opik_span(name, kind=kind, root=True, thread_id=thread_id, tags=tags)


def _close(span: Any, trace: Any | None, recorder: SpanRecorder) -> None:
    payload = recorder._payload()
    try:
        span.end(**payload)
    except Exception as err:  # noqa: BLE001 - a lost span is not a failed request
        _disable("span close failed", err)
        return
    if trace is None:
        return
    try:
        trace.end(
            output=payload.get("output"),
            metadata=payload.get("metadata"),
            error_info=payload.get("error_info"),
        )
    except Exception as err:  # noqa: BLE001
        _disable("trace close failed", err)
