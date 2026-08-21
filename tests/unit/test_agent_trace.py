"""The agent reports what it is doing, and reporting can never cost an answer.

The trace exists so a waiting user sees real search steps rather than a spinner.
That makes it commentary on the work, and the tests here pin the consequence: a
sink that is absent, slow to matter, or outright broken changes nothing about
the answer the agent produces.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from src.core.config import Settings
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
        return self.completions.pop(0)


def _completion(message: dict[str, Any]) -> ChatCompletion:
    return ChatCompletion(
        message=message,
        finish_reason="tool_calls" if message.get("tool_calls") else "stop",
        model="test-model",
        provider="primary",
        fallback_used=False,
        prompt_tokens=1,
        completion_tokens=0,
        total_tokens=1,
        latency_ms=1,
    )


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
                    "arguments": json.dumps({"query": query}, ensure_ascii=False),
                },
            }
        ],
    }


def _registry(*, similarity: float | None = 0.61) -> AgentToolRegistry:
    async def handler(arguments: ToolInput) -> list[dict[str, Any]]:
        evidence: dict[str, Any] = {
            "evidence_id": "chunk:1",
            "text": "evidence",
            "citation": {
                "url": "https://docs.liara.ir/paas/python#deploy",
                "page_title": "Python deployment",
                "section_title": "Deploy",
                "source_commit": "abc123",
            },
        }
        if similarity is not None:
            evidence["similarity"] = similarity
        return [evidence]

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
        "agent_timeout_seconds": 5,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_each_tool_call_reports_its_query_and_what_came_back() -> None:
    steps: list[Mapping[str, Any]] = []

    async def sink(step: Mapping[str, Any]) -> None:
        steps.append(dict(step))

    result = await BoundedAgent(
        ScriptedModel(
            [
                _completion(_tool_call("استقرار جنگو")),
                _completion(_answer("پاسخ مستند", "chunk:1")),
            ]
        ),
        _registry(),
        _settings(),
    ).run(RecordingExecutor(), question="استقرار جنگو", on_trace=sink)  # type: ignore[arg-type]

    assert result.content == "پاسخ مستند"
    assert len(steps) == 1
    step = steps[0]
    assert step["step"] == 1
    assert step["tool"] == "search_docs"
    # The query as the model wrote it, not its normalized form: this is shown to
    # a person, and the normalized form is not what they would recognize.
    assert step["query"] == "استقرار جنگو"
    assert step["result_count"] == 1
    assert step["top_similarity"] == pytest.approx(0.61)
    assert step["status"] == "ok"
    assert isinstance(step["elapsed_ms"], int)


@pytest.mark.asyncio
async def test_steps_are_numbered_in_the_order_they_happened() -> None:
    steps: list[Mapping[str, Any]] = []

    async def sink(step: Mapping[str, Any]) -> None:
        steps.append(dict(step))

    await BoundedAgent(
        ScriptedModel(
            [
                _completion(_tool_call("پرسش اول", call_id="a")),
                _completion(_tool_call("پرسش دوم", call_id="b")),
                _completion(_answer("پاسخ", "chunk:1")),
            ]
        ),
        _registry(),
        _settings(),
    ).run(RecordingExecutor(), question="پرسش اول", on_trace=sink)  # type: ignore[arg-type]

    assert [step["step"] for step in steps] == [1, 2]
    assert [step["query"] for step in steps] == ["پرسش اول", "پرسش دوم"]


@pytest.mark.asyncio
async def test_a_tool_result_without_similarity_reports_none_rather_than_zero() -> None:
    """Zero similarity is a measurement; "not reported" is not the same claim."""
    steps: list[Mapping[str, Any]] = []

    async def sink(step: Mapping[str, Any]) -> None:
        steps.append(dict(step))

    await BoundedAgent(
        ScriptedModel(
            [
                _completion(_tool_call("پرسش")),
                _completion(_answer("پاسخ", "chunk:1")),
            ]
        ),
        _registry(similarity=None),
        _settings(),
    ).run(RecordingExecutor(), question="پرسش", on_trace=sink)  # type: ignore[arg-type]

    assert steps[0]["top_similarity"] is None
    assert steps[0]["result_count"] == 1


@pytest.mark.asyncio
async def test_reaching_the_tool_call_limit_is_reported_as_a_step() -> None:
    steps: list[Mapping[str, Any]] = []

    async def sink(step: Mapping[str, Any]) -> None:
        steps.append(dict(step))

    await BoundedAgent(
        ScriptedModel(
            [
                _completion(_tool_call("پرسش")),
                _completion(_answer("پاسخ", "chunk:1")),
            ]
        ),
        _registry(),
        _settings(agent_max_tool_calls=0),
    ).run(RecordingExecutor(), question="پرسش", on_trace=sink)  # type: ignore[arg-type]

    # With no tool budget the loop goes straight to a tool-free final step, so
    # nothing is dispatched and nothing is reported. The user sees the answer
    # arrive without a fabricated search step in front of it.
    assert steps == []


@pytest.mark.asyncio
async def test_a_failing_sink_does_not_fail_the_turn() -> None:
    async def broken(step: Mapping[str, Any]) -> None:
        raise RuntimeError("relay is down")

    with pytest.raises(RuntimeError):
        # The agent itself does not swallow the failure — the worker's publisher
        # does, which is where the relay is known to be optional. Pinned here so
        # nobody "fixes" it by silencing errors inside the loop.
        await BoundedAgent(
            ScriptedModel(
                [
                    _completion(_tool_call("پرسش")),
                    _completion(_answer("پاسخ", "chunk:1")),
                ]
            ),
            _registry(),
            _settings(),
        ).run(RecordingExecutor(), question="پرسش", on_trace=broken)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_no_sink_means_no_behavior_change() -> None:
    result = await BoundedAgent(
        ScriptedModel(
            [
                _completion(_tool_call("پرسش")),
                _completion(_answer("پاسخ مستند", "chunk:1")),
            ]
        ),
        _registry(),
        _settings(),
    ).run(RecordingExecutor(), question="پرسش")  # type: ignore[arg-type]

    assert result.content == "پاسخ مستند"
    assert result.tool_calls == 1
