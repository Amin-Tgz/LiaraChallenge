"""An unreachable telemetry backend must cost telemetry, never a user's answer.

Task 14.6's acceptance criterion, and RULES.md §1's last line. Opik is pointed
at a closed port here, so the SDK is real, its client is real, and every send
genuinely fails — the assertion is that the agent turn and the chat completion
still return.

These tests need no database: telemetry sits between the caller and the
provider, which is exactly the seam being exercised.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import httpx
import pytest

from src.core.config import Settings, get_settings
from src.core.tracing import configure_tracing, reset_tracing_for_tests, shutdown_tracing
from src.services.agent import BoundedAgent
from src.services.agent_tools import AgentToolName, AgentToolRegistry, ToolInput
from src.services.gateway import ChatCompletion, GatewayChatClient

#: Port 1 is reserved and never listening: connections are refused at once,
#: so the test measures "telemetry is broken", not "telemetry is slow".
UNREACHABLE_OPIK = "http://127.0.0.1:1/opik/api"


@pytest.fixture
def unreachable_opik(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # The SDK's sender thread logs a full traceback per dropped span. Expected
    # here, and a screenful of them in a green suite teaches people to stop
    # reading test output.
    logging.getLogger("opik").setLevel(logging.CRITICAL)
    monkeypatch.setenv("OPIK_ENABLED", "true")
    monkeypatch.setenv("OPIK_API_KEY", "integration-test-key")
    monkeypatch.setenv("OPIK_WORKSPACE", "integration-test-workspace")
    monkeypatch.setenv("OPIK_URL_OVERRIDE", UNREACHABLE_OPIK)
    monkeypatch.setenv("OPIK_PROJECT_NAME", "liara-rescue-tests")
    monkeypatch.setenv("OPIK_FLUSH_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()
    reset_tracing_for_tests()
    # Configuration must succeed against a dead host — the client is built
    # locally and only its sends fail. If this returns False the rest of the
    # test would silently exercise the disabled path instead.
    assert configure_tracing() is True
    yield
    shutdown_tracing()
    reset_tracing_for_tests()
    get_settings.cache_clear()


class RecordingExecutor:
    def __init__(self) -> None:
        self.params: list[dict[str, Any]] = []

    async def execute(self, statement: Any) -> None:
        self.params.append(dict(statement.compile().params))


class ScriptedModel:
    def __init__(self, completions: Sequence[ChatCompletion]) -> None:
        self.completions = list(completions)

    async def complete(
        self,
        executor: Any,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        response_format: Mapping[str, Any] | None = None,
        reasoning_effort: str | None = None,
        telemetry: Any = None,
    ) -> ChatCompletion:
        return self.completions.pop(0)


def _completion(message: dict[str, Any]) -> ChatCompletion:
    return ChatCompletion(
        message=message,
        finish_reason="tool_calls" if message.get("tool_calls") else "stop",
        model="test-model",
        provider="primary",
        fallback_used=False,
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        latency_ms=1,
    )


def _tool_call(query: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "search_docs",
                    "arguments": json.dumps({"query": query}, ensure_ascii=False),
                },
            }
        ],
    }


def _answer(answer: str, *citation_ids: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": json.dumps(
            {
                "response_type": "answer",
                "answer": answer,
                "citation_ids": list(citation_ids),
                "clarification_question": None,
                "required_field": None,
            },
            ensure_ascii=False,
        ),
    }


def _registry(calls: list[str]) -> AgentToolRegistry:
    async def handler(arguments: ToolInput) -> dict[str, Any]:
        calls.append(getattr(arguments, "query", ""))
        return {
            "evidence_id": "chunk:1",
            "text": "متغیرها از بخش تنظیمات برنامه اضافه می‌شوند.",
            "similarity": 0.82,
            "citation": {
                "url": "https://docs.liara.ir/paas/details/envs/",
                "page_title": "متغیرهای محیطی",
                "section_title": "افزودن متغیر",
                "source_commit": "abc123",
            },
        }

    return AgentToolRegistry(
        {
            AgentToolName.SEARCH_DOCS: handler,
            AgentToolName.READ_DOC: handler,
            AgentToolName.SEARCH_RELATED_QUESTIONS: handler,
        }
    )


@pytest.mark.asyncio
async def test_agent_turn_completes_while_opik_refuses_every_span(
    unreachable_opik: None,
) -> None:
    calls: list[str] = []
    model = ScriptedModel(
        [
            _completion(_tool_call("متغیر محیطی")),
            _completion(_answer("از بخش تنظیمات، متغیرها را اضافه کنید.", "chunk:1")),
        ]
    )
    settings = Settings(
        _env_file=None,
        opik_enabled=True,
        opik_api_key="integration-test-key",
        opik_workspace="integration-test-workspace",
        opik_url_override=UNREACHABLE_OPIK,
        agent_max_tool_calls=3,
        agent_max_rewrites=2,
        agent_token_budget=100,
        agent_timeout_seconds=30,
    )

    result = await BoundedAgent(model, _registry(calls), settings).run(
        RecordingExecutor(),  # type: ignore[arg-type]
        question="چطور متغیر محیطی تنظیم کنم؟",
    )

    # The turn span, the tool span, and the trace all failed to ship. None of
    # that is visible here, which is the whole point.
    assert result.content == "از بخش تنظیمات، متغیرها را اضافه کنید."
    assert result.tool_calls == 1
    assert calls == ["متغیر محیطی"]
    assert len(result.citations) == 1
    assert result.error_code is None


@pytest.mark.asyncio
async def test_chat_completion_succeeds_while_opik_refuses_every_span(
    unreachable_opik: None,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "primary-model",
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": "پاسخ"}}
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
            },
        )

    settings = Settings(
        _env_file=None,
        opik_enabled=True,
        opik_api_key="integration-test-key",
        opik_workspace="integration-test-workspace",
        opik_url_override=UNREACHABLE_OPIK,
        portkey_base_url="http://gateway:8787",
        llm_base_url="https://primary.example/v1",
        llm_api_key="primary-test-key",
        llm_model="primary-model",
    )
    client = GatewayChatClient(
        settings,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async with client:
        completion = await client.complete(
            RecordingExecutor(),  # type: ignore[arg-type]
            messages=[{"role": "user", "content": "سلام"}],
        )

    assert completion.message["content"] == "پاسخ"
    assert completion.total_tokens == 15
    assert completion.fallback_used is False
