"""The taxonomy's whole purpose is that two causes never look alike.

`NO_ACTIVE_INDEX` (the system is broken) and `NO_RESULTS_ABOVE_THRESHOLD` (the
system works and this is a real documentation gap) are indistinguishable to a
user unless something enforces the difference. That is what this file does.
"""

from __future__ import annotations

import pytest

from src.core.errors import ERROR_SPECS, ErrorCode, RescueError, spec_for


def test_every_code_has_a_spec() -> None:
    missing = [code for code in ErrorCode if code not in ERROR_SPECS]
    assert missing == [], f"codes without a spec: {missing}"


@pytest.mark.parametrize("code", list(ErrorCode))
def test_spec_is_complete(code: ErrorCode) -> None:
    spec = spec_for(code)
    assert spec.code is code
    assert spec.message_fa.strip(), f"{code} has no Persian message"
    assert spec.operator_action.strip(), f"{code} has no operator action"
    assert 200 <= spec.http_status < 600


@pytest.mark.parametrize("code", list(ErrorCode))
def test_message_is_persian_and_not_a_placeholder(code: ErrorCode) -> None:
    message = spec_for(code).message_fa
    assert any("؀" <= ch <= "ۿ" for ch in message), f"{code} message is not Persian"
    # The forbidden catch-all: a message that says nothing about the cause.
    assert "چیزی پیدا نکردم" not in message


def test_codes_are_distinct() -> None:
    values = [str(code) for code in ErrorCode]
    assert len(values) == len(set(values))


def test_messages_are_distinct() -> None:
    """Two different causes must never share a message."""
    by_message: dict[str, list[str]] = {}
    for code in ErrorCode:
        by_message.setdefault(spec_for(code).message_fa, []).append(str(code))
    collisions = {msg: codes for msg, codes in by_message.items() if len(codes) > 1}
    assert collisions == {}, f"codes sharing a message: {collisions}"


def test_empty_index_and_empty_result_are_not_interchangeable() -> None:
    broken = spec_for(ErrorCode.NO_ACTIVE_INDEX)
    working = spec_for(ErrorCode.NO_RESULTS_ABOVE_THRESHOLD)

    assert broken.message_fa != working.message_fa
    assert broken.operator_action != working.operator_action
    # One is an outage the platform must withhold traffic for; the other is a
    # successful response carrying the product's most valuable analytics signal.
    assert broken.http_status == 503
    assert working.http_status == 200


def test_transient_classification_drives_retry() -> None:
    """Timeouts and 5xx retry; validation and auth fail fast."""
    assert spec_for(ErrorCode.UPSTREAM_TIMEOUT).transient is True
    assert spec_for(ErrorCode.RETRIEVAL_FAILED).transient is True
    assert spec_for(ErrorCode.ALL_PROVIDERS_UNAVAILABLE).transient is True
    assert spec_for(ErrorCode.INVALID_REQUEST).transient is False
    assert spec_for(ErrorCode.UNAUTHORIZED).transient is False
    assert spec_for(ErrorCode.NO_ACTIVE_INDEX).transient is False


def test_rescue_error_preserves_cause_and_hides_detail_from_users() -> None:
    original = ValueError("asyncpg: connection refused to 10.0.0.4:5432")
    try:
        try:
            raise original
        except ValueError as err:
            raise RescueError(
                ErrorCode.RETRIEVAL_FAILED,
                detail=str(err),
                context={"index_version": "7"},
            ) from err
    except RescueError as err:
        assert err.__cause__ is original
        assert err.http_status == 503
        body = err.to_response()
        assert body["error"]["code"] == "RETRIEVAL_FAILED"
        assert body["error"]["message"] == err.spec.message_fa
        # Operator detail must not leak into the user-facing payload.
        assert "10.0.0.4" not in body["error"]["message"]
        assert "asyncpg" not in body["error"]["message"]
    else:  # pragma: no cover
        pytest.fail("RescueError was not raised")
