from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from src.core.config import Settings
from src.services.agent import BoundedAgent
from src.services.agent_tools import AgentToolName, AgentToolRegistry, ToolInput
from src.services.gateway import ChatCompletion, GatewayTelemetry


class Executor:
    async def execute(self, statement: Any) -> None:
        return None


class ScriptedModel:
    def __init__(self, messages: Sequence[dict[str, Any]]) -> None:
        self.messages = list(messages)
        self.calls = 0

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
        self.calls += 1
        return ChatCompletion(
            message=self.messages.pop(0),
            finish_reason="stop",
            model="test",
            provider="primary",
            fallback_used=False,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=1,
        )


def _tool_call() -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "search_docs",
                    "arguments": '{"query":"چطور متغیر محیطی ثبت کنم؟"}',
                },
            }
        ],
    }


def _clarification(field: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": json.dumps(
            {
                "response_type": "clarification",
                "answer": None,
                "citation_ids": [],
                "clarification_question": "از کدام runtime استفاده می‌کنید؟",
                "required_field": field,
            },
            ensure_ascii=False,
        ),
    }


def _answer() -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": json.dumps(
            {
                "response_type": "answer",
                "answer": "متغیر را در تنظیمات برنامه ثبت کنید.",
                "citation_ids": ["chunk:1"],
                "clarification_question": None,
                "required_field": None,
            },
            ensure_ascii=False,
        ),
    }


def _evidence(*runtimes: str) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": f"chunk:{position}",
            "text": "راهنمای متغیر محیطی",
            "metadata": {"runtime": runtime},
            "citation": {
                "url": f"https://docs.liara.ir/paas/{runtime}#envs",
                "page_title": f"{runtime} guide",
                "section_title": "Environment variables",
                "source_commit": "dbb7430",
            },
        }
        for position, runtime in enumerate(runtimes, 1)
    ]


def _registry(evidence: list[dict[str, Any]]) -> AgentToolRegistry:
    async def handler(arguments: ToolInput) -> list[dict[str, Any]]:
        return evidence

    return AgentToolRegistry(
        {
            AgentToolName.SEARCH_DOCS: handler,
            AgentToolName.READ_DOC: handler,
            AgentToolName.SEARCH_RELATED_QUESTIONS: handler,
        }
    )


@pytest.mark.asyncio
async def test_answer_invariant_question_is_answered_without_clarification() -> None:
    model = ScriptedModel([_tool_call(), _clarification("runtime"), _answer()])

    result = await BoundedAgent(
        model,
        _registry(_evidence("python", "python")),
        Settings(_env_file=None),
    ).run(Executor(), question="چطور متغیر محیطی ثبت کنم؟")  # type: ignore[arg-type]

    assert model.calls == 3
    assert result.needs_clarification is False
    assert result.content == "متغیر را در تنظیمات برنامه ثبت کنید."
    assert result.citations[0].url == "https://docs.liara.ir/paas/python#envs"


@pytest.mark.asyncio
async def test_clarification_is_allowed_when_runtime_changes_the_evidence() -> None:
    model = ScriptedModel([_tool_call(), _clarification("runtime")])

    result = await BoundedAgent(
        model,
        _registry(_evidence("python", "nodejs")),
        Settings(_env_file=None),
    ).run(Executor(), question="چطور متغیر محیطی ثبت کنم؟")  # type: ignore[arg-type]

    assert model.calls == 2
    assert result.needs_clarification is True
    assert result.clarification_field == "runtime"
    assert result.citations == ()
