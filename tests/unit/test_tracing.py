"""Opik tracing: what it sends, what it withholds, and when it loads at all."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.core.config import Settings, get_settings
from src.core.tracing import (
    SpanRecorder,
    configure_tracing,
    opik_span,
    reset_tracing_for_tests,
    tracing_enabled,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def tracing_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin the ambient switch, so a developer's local .env cannot flip these."""
    monkeypatch.setenv("OPIK_ENABLED", "false")
    get_settings.cache_clear()
    reset_tracing_for_tests()
    yield
    get_settings.cache_clear()
    reset_tracing_for_tests()


def _live(*, capture_content: bool = True) -> SpanRecorder:
    return SpanRecorder(_live=True, _capture_content=capture_content)


def test_tracing_is_off_without_a_key_or_a_workspace() -> None:
    enabled_but_unconfigured = Settings(
        _env_file=None,
        opik_enabled=True,
        opik_api_key="",
        opik_workspace="",
    )
    keyed_but_disabled = Settings(
        _env_file=None,
        opik_enabled=False,
        opik_api_key="k",
        opik_workspace="w",
    )

    assert tracing_enabled(Settings(_env_file=None, opik_enabled=False)) is False
    assert tracing_enabled(enabled_but_unconfigured) is False
    assert tracing_enabled(keyed_but_disabled) is False
    assert configure_tracing(keyed_but_disabled) is False


def test_a_disabled_span_records_nothing_and_still_yields_a_recorder() -> None:
    with opik_span("retrieval.search_documentation", kind="tool") as span:
        span.metadata(result_count=3)
        span.content(query="چطور دامنه وصل کنم؟")

    assert span.captures_content is False
    assert span._payload() == {}


def test_the_opik_sdk_is_not_imported_while_tracing_is_disabled() -> None:
    # A disabled deployment must not pay for the SDK: no import, so no client,
    # no queue, and no background sender thread.
    script = (
        "import sys;"
        "from src.core.tracing import opik_span;"
        "ctx = opik_span('probe');"
        "ctx.__enter__();"
        "ctx.__exit__(None, None, None);"
        "print('opik' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env={**os.environ, "OPIK_ENABLED": "false"},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )

    assert result.stdout.strip() == "False", result.stderr


def test_credentials_never_reach_a_span_payload() -> None:
    span = _live()
    span.content(
        messages=[
            {"role": "system", "content": "Bearer sk-live-abcdefghijklmnop is the key"},
            {"role": "user", "content": "چرا خطا می‌گیرم؟"},
        ]
    )
    span.metadata(
        authorization="Bearer sk-live-abcdefghijklmnop",
        llm_api_key="aa-secret-value-1234",
        database_url="postgresql+asyncpg://user:pw@host/db",
        nested={"headers": {"Cookie": "rescue_session=abc"}},
        result_count=3,
    )
    span.error("UNAUTHORIZED", "provider rejected the credential")

    payload = span._payload()
    flattened = repr(payload)

    assert "sk-live-abcdefghijklmnop" not in flattened
    assert "aa-secret-value-1234" not in flattened
    assert "rescue_session=abc" not in flattened
    assert ":pw@host" not in flattened
    # Redaction is targeted, not indiscriminate: the operator still gets the
    # numbers and the error code that make the span worth sending.
    assert payload["metadata"]["result_count"] == 3
    assert payload["error_info"]["exception_type"] == "UNAUTHORIZED"
    assert payload["input"]["messages"][1]["content"] == "چرا خطا می‌گیرم؟"


def test_content_capture_off_keeps_the_measurements_and_drops_the_text() -> None:
    span = _live(capture_content=False)
    span.content(query="چطور متغیر محیطی تنظیم کنم؟")
    span.content_output(answer="از بخش تنظیمات…")
    span.metadata(result_count=5, top_similarity=0.71, similarity_threshold=0.35)
    span.usage(model="gemini-3.7-flash", provider="primary", total_tokens=120)

    payload = span._payload()

    assert span.captures_content is False
    assert "input" not in payload
    assert "output" not in payload
    assert payload["metadata"] == {
        "result_count": 5,
        "top_similarity": 0.71,
        "similarity_threshold": 0.35,
    }
    assert payload["usage"] == {"total_tokens": 120}
    assert payload["model"] == "gemini-3.7-flash"
