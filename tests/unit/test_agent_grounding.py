from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from src.core.config import Settings
from src.core.errors import ErrorCode
from src.services.agent import BoundedAgent
from src.services.agent_tools import AgentToolName, AgentToolRegistry, ToolInput
from src.services.gateway import ChatCompletion, GatewayTelemetry


class RecordingExecutor:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def execute(self, statement: Any) -> None:
        self.events.append(dict(statement.compile().params))


class ScriptedModel:
    def __init__(self, messages: Sequence[dict[str, Any]]) -> None:
        self.messages = list(messages)

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
        assert response_format is not None
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
                "function": {"name": "search_docs", "arguments": '{"query":"django"}'},
            }
        ],
    }


def _answer(citation_id: str | None) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": json.dumps(
            {
                "response_type": "answer",
                "answer": "مقدار متغیر را در تنظیمات برنامه ثبت کنید.",
                "citation_ids": [citation_id] if citation_id else [],
                "clarification_question": None,
                "required_field": None,
            },
            ensure_ascii=False,
        ),
    }


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


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_unanswerable_question_abstains_with_no_evidence() -> None:
    executor = RecordingExecutor()
    result = await BoundedAgent(
        ScriptedModel([_answer(None)]),
        _registry([]),
        _settings(),
    ).run(
        executor,  # type: ignore[arg-type]
        question="آیا لیارا روی ماه دیتاسنتر دارد؟",
        telemetry=GatewayTelemetry(trace_id="no-evidence", question="سؤال بی‌پاسخ"),
    )

    assert result.error_code is ErrorCode.NO_EVIDENCE
    assert result.citations == ()
    assert "حدس" in result.content
    assert executor.events[-1]["error_code"] == "NO_EVIDENCE"
    assert executor.events[-1]["question"] == "سؤال بی‌پاسخ"


@pytest.mark.asyncio
async def test_citations_are_reconstructed_from_retrieved_public_deep_links() -> None:
    evidence = [
        {
            "evidence_id": "chunk:django-envs",
            "text": "متغیرها را در تنظیمات برنامه وارد کنید.",
            "metadata": {"source_path": "src/pages/paas/django/getting-started.mdx"},
            "images": [
                {
                    "url": "https://media.liara.ir/django-envs.png",
                    "alt": "فرم متغیرهای محیطی",
                    "ordinal": 2,
                    "heading_anchor": "envs",
                },
                {"url": "javascript:alert(1)", "alt": "نامعتبر"},
            ],
            "citation": {
                "url": "https://docs.liara.ir/paas/django/getting-started#envs",
                "page_title": "شروع کار با Django",
                "section_title": "متغیرهای محیطی",
                "source_commit": "dbb7430",
            },
        },
        {
            "evidence_id": "chunk:uncited",
            "text": "راهنمای نامرتبط",
            "metadata": {"source_path": "src/pages/paas/nodejs/about.mdx"},
            "images": [
                {
                    "url": "https://media.liara.ir/uncited.png",
                    "alt": "تصویر شاهد ارجاع‌نشده",
                }
            ],
            "citation": {
                "url": "https://docs.liara.ir/paas/nodejs#about",
                "page_title": "Node.js",
                "section_title": "معرفی",
                "source_commit": "dbb7430",
            },
        },
    ]
    result = await BoundedAgent(
        ScriptedModel([_tool_call(), _answer("chunk:django-envs")]),
        _registry(evidence),
        _settings(),
    ).run(RecordingExecutor(), question="متغیر جنگو را کجا ثبت کنم؟")  # type: ignore[arg-type]

    assert result.error_code is None
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.url == "https://docs.liara.ir/paas/django/getting-started#envs"
    assert citation.page_title == "شروع کار با Django"
    assert citation.section_title == "متغیرهای محیطی"
    assert "src/pages" not in citation.url
    assert result.images == (
        {
            "evidence_id": "chunk:django-envs",
            "url": "https://media.liara.ir/django-envs.png",
            "alt": "فرم متغیرهای محیطی",
            "ordinal": 2,
            "heading_anchor": "envs",
        },
    )


@pytest.mark.asyncio
async def test_model_cannot_cite_evidence_that_was_not_retrieved() -> None:
    result = await BoundedAgent(
        ScriptedModel([_tool_call(), _answer("chunk:fabricated")]),
        _registry([]),
        _settings(),
    ).run(RecordingExecutor(), question="سؤال")  # type: ignore[arg-type]

    assert result.error_code is ErrorCode.NO_EVIDENCE
    assert result.citations == ()
