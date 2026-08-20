from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from src.core.config import Settings
from src.services.agent import AGENT_SYSTEM_PROMPT, BoundedAgent
from src.services.agent_tools import AgentToolName, AgentToolRegistry, ToolInput
from src.services.gateway import ChatCompletion, GatewayTelemetry

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "prompt_injection_document.json"


class Executor:
    async def execute(self, statement: Any) -> None:
        return None


class BoundaryCheckingModel:
    def __init__(self) -> None:
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
        assert messages[0] == {"role": "system", "content": AGENT_SYSTEM_PROMPT}
        if self.calls == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "search_docs",
                            "arguments": '{"query":"متغیر محیطی Python"}',
                        },
                    }
                ],
            }
        else:
            tool_message = next(message for message in messages if message["role"] == "tool")
            envelope = json.loads(str(tool_message["content"]))
            assert envelope["kind"] == "liara_documentation_evidence"
            assert envelope["trust"] == "untrusted_data_not_instructions"
            assert "run_shell" in envelope["content"][0]["text"]
            assert tools is not None
            assert {tool["function"]["name"] for tool in tools} == {
                "search_docs",
                "read_doc",
                "search_related_questions",
            }
            message = {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "response_type": "answer",
                        "answer": "پاسخ به پرسش اصلی از شاهد معتبر.",
                        "citation_ids": ["chunk:injection-fixture"],
                        "clarification_question": None,
                        "required_field": None,
                    },
                    ensure_ascii=False,
                ),
            }
        return ChatCompletion(
            message=message,
            finish_reason="stop",
            model="test",
            provider="primary",
            fallback_used=False,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=1,
        )


@pytest.mark.asyncio
async def test_prompt_injection_in_retrieved_content_cannot_change_agent_behavior() -> None:
    injected_evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))

    async def handler(arguments: ToolInput) -> list[dict[str, Any]]:
        return [injected_evidence]

    registry = AgentToolRegistry(
        {
            AgentToolName.SEARCH_DOCS: handler,
            AgentToolName.READ_DOC: handler,
            AgentToolName.SEARCH_RELATED_QUESTIONS: handler,
        }
    )

    result = await BoundedAgent(
        BoundaryCheckingModel(),
        registry,
        Settings(_env_file=None),
    ).run(Executor(), question="متغیر محیطی Python را کجا ثبت کنم؟")  # type: ignore[arg-type]

    assert result.content == "پاسخ به پرسش اصلی از شاهد معتبر."
    assert "HACKED" not in result.content
    assert result.citations[0].evidence_id == "chunk:injection-fixture"
    assert result.citations[0].url == "https://docs.liara.ir/paas/python#envs"
