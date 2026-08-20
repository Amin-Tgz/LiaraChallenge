"""The embedding client's two silent failure modes, plus retry classification.

A wrong dimension and a reordered batch both produce vectors that look fine and
retrieve wrongly. Both are checked here against a mock transport, so no provider
call is made.
"""

from __future__ import annotations

import httpx
import pytest

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.services.embeddings import (
    CUSTOM_HOST_HEADER,
    PROVIDER_HEADER,
    EmbeddingClient,
)

DIM = 1536


def _settings(**overrides: object) -> Settings:
    return Settings(  # type: ignore[arg-type]
        _env_file=None,
        embedding_api_key="test-key",
        portkey_base_url="http://gateway:8787",
        embedding_base_url="https://provider.example/v1",
        embedding_dimensions=DIM,
        embedding_batch_size=2,
        **overrides,
    )


def _client(handler, **overrides: object) -> EmbeddingClient:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    return EmbeddingClient(
        _settings(**overrides), client=httpx.Client(transport=transport, timeout=5)
    )


def _ok(request: httpx.Request, *, dimensions: int = DIM, reverse: bool = False) -> httpx.Response:
    import json

    inputs = json.loads(request.content)["input"]
    rows = [
        {"object": "embedding", "index": i, "embedding": [float(i)] * dimensions}
        for i, _ in enumerate(inputs)
    ]
    if reverse:
        rows.reverse()
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": "text-embedding-3-large",
            "data": rows,
            "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
        },
    )


def test_routes_through_the_gateway_with_provider_headers() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["provider"] = request.headers.get(PROVIDER_HEADER)
        seen["custom_host"] = request.headers.get(CUSTOM_HOST_HEADER)
        seen["auth"] = request.headers.get("authorization")
        return _ok(request)

    with _client(handler) as client:
        client.embed_one("سلام")

    assert seen["url"] == "http://gateway:8787/v1/embeddings"
    assert seen["provider"] == "openai"
    # The provider is reached *through* the gateway, never addressed directly —
    # bypassing it would lose retries, backoff, and fallback.
    assert seen["custom_host"] == "https://provider.example/v1"
    assert seen["auth"] == "Bearer test-key"


def test_requests_the_configured_dimensions() -> None:
    import json

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _ok(request)

    with _client(handler) as client:
        client.embed_one("سلام")

    assert seen["dimensions"] == DIM


def test_batches_at_the_configured_size() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        calls.append(len(json.loads(request.content)["input"]))
        return _ok(request)

    with _client(handler) as client:  # embedding_batch_size=2
        result = client.embed(["a", "b", "c", "d", "e"])

    assert calls == [2, 2, 1]
    assert len(result.vectors) == 5
    assert result.total_tokens == 5


def test_vectors_are_realigned_by_reported_index() -> None:
    """Batching must not become a semantic change."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok(request, reverse=True)

    with _client(handler) as client:
        result = client.embed_batch(["first", "second"])

    assert result.vectors[0][0] == 0.0
    assert result.vectors[1][0] == 1.0


def test_wrong_dimension_is_refused_with_its_own_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok(request, dimensions=3072)

    with _client(handler) as client, pytest.raises(RescueError) as caught:
        client.embed_one("سلام")

    assert caught.value.code is ErrorCode.EMBEDDING_FAILED
    assert "3072" in (caught.value.detail or "")


def test_short_response_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.0] * DIM}], "usage": {}},
        )

    with _client(handler) as client, pytest.raises(RescueError) as caught:
        client.embed_batch(["a", "b"])

    assert caught.value.code is ErrorCode.EMBEDDING_FAILED


def test_auth_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.embeddings.time.sleep", lambda _: None)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": "bad key"})

    with _client(handler) as client, pytest.raises(RescueError) as caught:
        client.embed_one("سلام")

    assert caught.value.code is ErrorCode.UNAUTHORIZED
    assert attempts == 1, "an invalid credential fails identically every time"
    assert "bad key" not in str(caught.value)


def test_transient_failure_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.embeddings.time.sleep", lambda _: None)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "upstream busy"})
        return _ok(request)

    with _client(handler) as client:
        vector = client.embed_one("سلام")

    assert attempts == 2
    assert len(vector) == DIM


def test_exhausted_retries_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.embeddings.time.sleep", lambda _: None)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, json={"error": "boom"})

    with _client(handler) as client, pytest.raises(RescueError) as caught:
        client.embed_one("سلام")

    assert caught.value.code is ErrorCode.EMBEDDING_FAILED
    assert attempts == 3, "retries must terminate rather than loop"


def test_server_supplied_delay_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("src.services.embeddings.time.sleep", slept.append)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"retry-after": "7"}, json={"error": "slow down"})
        return _ok(request)

    with _client(handler) as client:
        client.embed_one("سلام")

    assert slept == [7.0]


def test_unreachable_gateway_names_that_cause() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with _client(handler) as client, pytest.raises(RescueError) as caught:
        client.embed_one("سلام")

    assert caught.value.code is ErrorCode.ALL_PROVIDERS_UNAVAILABLE


def test_empty_input_costs_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not run
        raise AssertionError("no request should be made for an empty batch")

    with _client(handler) as client:
        result = client.embed([])

    assert result.vectors == []
