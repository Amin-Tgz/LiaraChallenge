from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.services.embeddings import CUSTOM_HOST_HEADER, PROVIDER_HEADER
from src.services.gateway import GatewayChatClient, GatewayTelemetry


class RecordingExecutor:
    def __init__(self) -> None:
        self.params: list[dict[str, Any]] = []

    async def execute(self, statement: Any) -> None:
        self.params.append(dict(statement.compile().params))


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        portkey_base_url="http://gateway:8787",
        llm_base_url="https://primary.example/v1",
        llm_api_key="primary-test-key",
        llm_model="primary-model",
        portkey_fallback_base_url="https://fallback.example/v1",
        portkey_fallback_api_key="fallback-test-key",
        portkey_fallback_model="fallback-model",
    )


@pytest.mark.asyncio
async def test_transient_primary_failure_uses_fallback_and_records_it() -> None:
    calls: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        call = {
            "url": str(request.url),
            "provider": request.headers.get(PROVIDER_HEADER),
            "host": request.headers.get(CUSTOM_HOST_HEADER),
            "authorization": request.headers.get("authorization"),
            "body": json.loads(request.content),
        }
        calls.append(call)
        if call["host"] == "https://primary.example/v1":
            return httpx.Response(503, json={"error": "primary unavailable"})
        return httpx.Response(
            200,
            json={
                "model": "fallback-model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "پاسخ"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 9,
                    "completion_tokens": 3,
                    "total_tokens": 12,
                },
            },
        )

    executor = RecordingExecutor()
    client = GatewayChatClient(
        _settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    completion = await client.complete(
        executor,  # type: ignore[arg-type]
        messages=[{"role": "user", "content": "سؤال"}],
        telemetry=GatewayTelemetry(trace_id="trace-9-1", question="سؤال"),
    )
    await client.client.aclose()

    assert len(calls) == 2
    assert calls[0]["url"] == "http://gateway:8787/v1/chat/completions"
    assert calls[0]["provider"] == calls[1]["provider"] == "openai"
    assert calls[0]["host"] == "https://primary.example/v1"
    assert calls[1]["host"] == "https://fallback.example/v1"
    assert calls[0]["authorization"] == "Bearer primary-test-key"
    assert calls[1]["authorization"] == "Bearer fallback-test-key"
    assert calls[0]["body"]["model"] == "primary-model"
    assert calls[1]["body"]["model"] == "fallback-model"
    assert completion.fallback_used is True
    assert completion.provider == "fallback"
    assert completion.message["content"] == "پاسخ"

    assert len(executor.params) == 1
    event = executor.params[0]
    assert event["event_type"] == "provider_fallback"
    assert event["fallback_used"] is True
    assert event["trace_id"] == "trace-9-1"
    assert event["provider"] == "fallback"
    assert event["model"] == "fallback-model"
    assert event["payload"]["primary_failure"] == "transient_http_status"
    serialized = json.dumps(event)
    assert "primary-test-key" not in serialized
    assert "fallback-test-key" not in serialized
    assert "primary.example" not in serialized
    assert "fallback.example" not in serialized


@pytest.mark.asyncio
async def test_primary_auth_failure_is_not_sent_to_fallback() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "credential echoed here"})

    client = GatewayChatClient(
        _settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RescueError) as caught:
        await client.complete(
            RecordingExecutor(),  # type: ignore[arg-type]
            messages=[{"role": "user", "content": "سؤال"}],
        )
    await client.client.aclose()

    assert caught.value.code is ErrorCode.UNAUTHORIZED
    assert calls == 1
    assert "credential echoed here" not in str(caught.value)
