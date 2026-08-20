"""No key, cookie, or token may reach a log record (RULES.md §4)."""

from __future__ import annotations

import json
import logging

import pytest

from src.core.logging import (
    JsonFormatter,
    RedactingTelemetryHandler,
    clear_correlation,
    get_correlation,
    redact,
    set_correlation,
)


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(autouse=True)
def _clean_correlation():
    clear_correlation()
    yield
    clear_correlation()


def _format(message: str, **extra: object) -> dict:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(JsonFormatter().format(record))


@pytest.mark.parametrize(
    "key",
    ["api_key", "LLM_API_KEY", "authorization", "password", "token", "cookie", "database_url"],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    assert redact({key: "super-secret-value"})[key] == "[REDACTED]"


def test_redaction_reaches_nested_structures() -> None:
    payload = {"request": {"headers": {"Authorization": "Bearer abcdef123456"}}, "ok": True}
    result = redact(payload)
    assert result["request"]["headers"]["Authorization"] == "[REDACTED]"
    assert result["ok"] is True


@pytest.mark.parametrize(
    "text",
    [
        "calling provider with sk-abcdef1234567890",
        "header was Bearer eyJhbGciOiJIUzI1NiJ9",
        "postgresql+asyncpg://rescue:hunter2@postgres:5432/rescue",
    ],
)
def test_secret_shaped_values_are_redacted_in_free_text(text: str) -> None:
    record = _format(text)
    assert "[REDACTED]" in record["message"]
    for leaked in ("sk-abcdef1234567890", "eyJhbGciOiJIUzI1NiJ9", "hunter2"):
        assert leaked not in record["message"]


def test_correlation_ids_are_attached_to_every_record() -> None:
    set_correlation(trace_id="t-1", job_id="j-9")
    record = _format("job progressed")
    assert record["trace_id"] == "t-1"
    assert record["job_id"] == "j-9"


def test_unknown_correlation_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown correlation key"):
        set_correlation(user_email="someone@example.com")
    assert get_correlation() == {}


def test_extras_are_redacted_before_emission() -> None:
    record = _format("provider call", error_code="EMBEDDING_FAILED", api_key="sk-live-9999999999")
    assert record["error_code"] == "EMBEDDING_FAILED"
    assert record["api_key"] == "[REDACTED]"


def test_telemetry_receives_only_the_redacted_json_record() -> None:
    delegate = _CaptureHandler()
    handler = RedactingTelemetryHandler(delegate)
    record = logging.LogRecord(
        name="src.services.provider",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="provider failed for postgresql://rescue:hunter2@postgres/rescue",
        args=(),
        exc_info=None,
    )
    record.api_key = "sk-live-9999999999"

    handler.emit(record)

    assert len(delegate.records) == 1
    exported = delegate.records[0].getMessage()
    assert "hunter2" not in exported
    assert "sk-live-9999999999" not in exported
    assert exported.count("[REDACTED]") == 2
