from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.services.agent import BoundedAgent
from src.services.agent_tools import AgentToolName, AgentToolRegistry, ToolInput
from src.services.gateway import ChatCompletion, GatewayTelemetry


class RecordingExecutor:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def execute(self, statement: Any) -> None:
        self.events.append(dict(statement.compile().params))


class ScriptedModel:
    def __init__(self, completions: Sequence[ChatCompletion]) -> None:
        self.completions = list(completions)
        self.tool_declarations: list[Sequence[Mapping[str, Any]] | None] = []

    async def complete(
        self,
        executor: Any,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        response_format: Mapping[str, Any] | None = None,
        reasoning_effort: str | None = None,
        telemetry: GatewayTelemetry | None = None,
    ) -> ChatCompletion:
        self.tool_declarations.append(tools)
        return self.completions.pop(0)


def _completion(message: dict[str, Any], *, total_tokens: int = 1) -> ChatCompletion:
    return ChatCompletion(
        message=message,
        finish_reason="tool_calls" if message.get("tool_calls") else "stop",
        model="test-model",
        provider="primary",
        fallback_used=False,
        prompt_tokens=total_tokens,
        completion_tokens=0,
        total_tokens=total_tokens,
        latency_ms=1,
    )


def _tool_call(query: str, *, call_id: str = "call-1") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "search_docs",
                    "arguments": '{"query":"' + query + '"}',
                },
            }
        ],
    }


def _registry(calls: list[str]) -> AgentToolRegistry:
    async def handler(arguments: ToolInput) -> dict[str, str]:
        query = getattr(arguments, "query", "")
        calls.append(query)
        return {"evidence": "مستند"}

    return AgentToolRegistry(
        {
            AgentToolName.SEARCH_DOCS: handler,
            AgentToolName.READ_DOC: handler,
            AgentToolName.SEARCH_RELATED_QUESTIONS: handler,
        }
    )


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "agent_max_tool_calls": 3,
        "agent_max_rewrites": 2,
        "agent_token_budget": 100,
        "agent_timeout_seconds": 1,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_tool_call_limit_forces_a_tool_free_final_step() -> None:
    calls: list[str] = []
    model = ScriptedModel(
        [
            _completion(_tool_call("سؤال")),
            _completion({"role": "assistant", "content": "پاسخ از شاهد"}),
        ]
    )
    executor = RecordingExecutor()

    result = await BoundedAgent(
        model,
        _registry(calls),
        _settings(agent_max_tool_calls=1),
    ).run(executor, question="سؤال")  # type: ignore[arg-type]

    assert calls == ["سؤال"]
    assert model.tool_declarations[0] is not None
    assert model.tool_declarations[1] is None
    assert result.limit_reason == "tool_calls"
    assert result.error_code is ErrorCode.AGENT_LIMIT_REACHED
    assert result.tool_calls == 1
    assert executor.events[-1]["payload"]["limit"] == "tool_calls"


@pytest.mark.asyncio
async def test_rewrite_limit_prevents_the_new_query_from_reaching_a_tool() -> None:
    calls: list[str] = []
    model = ScriptedModel(
        [
            _completion(_tool_call("عبارت بازنویسی شده")),
            _completion({"role": "assistant", "content": "شاهد کافی نیست"}),
        ]
    )

    result = await BoundedAgent(
        model,
        _registry(calls),
        _settings(agent_max_rewrites=0),
    ).run(RecordingExecutor(), question="سؤال اصلی")  # type: ignore[arg-type]

    assert calls == []
    assert result.limit_reason == "rewrites"
    assert result.rewrites == 0


@pytest.mark.asyncio
async def test_token_budget_terminates_the_turn() -> None:
    model = ScriptedModel(
        [_completion({"role": "assistant", "content": "نباید تحویل شود"}, total_tokens=11)]
    )
    executor = RecordingExecutor()

    with pytest.raises(RescueError) as caught:
        await BoundedAgent(
            model,
            _registry([]),
            _settings(agent_token_budget=10),
        ).run(executor, question="سؤال")  # type: ignore[arg-type]

    assert caught.value.code is ErrorCode.AGENT_LIMIT_REACHED
    assert executor.events[-1]["payload"]["limit"] == "tokens"


@pytest.mark.asyncio
async def test_timeout_terminates_and_records_its_distinct_cause() -> None:
    class SlowModel(ScriptedModel):
        async def complete(self, *args: Any, **kwargs: Any) -> ChatCompletion:
            await asyncio.sleep(1)
            raise AssertionError("timeout should cancel the provider wait")

    executor = RecordingExecutor()
    with pytest.raises(RescueError) as caught:
        await BoundedAgent(
            SlowModel([]),
            _registry([]),
            _settings(agent_timeout_seconds=0.01),
        ).run(executor, question="سؤال")  # type: ignore[arg-type]

    assert caught.value.code is ErrorCode.UPSTREAM_TIMEOUT
    assert executor.events[-1]["error_code"] == "UPSTREAM_TIMEOUT"
    assert executor.events[-1]["payload"]["limit"] == "timeout"
