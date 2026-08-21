from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.services.agent_tools import (
    AGENT_TOOL_DEFINITIONS,
    AGENT_TOOL_NAMES,
    AgentToolName,
    AgentToolRegistry,
    ToolInput,
    _chunk_evidence,
    build_documentation_tool_registry,
)
from src.services.retrieval import RetrievalResult


def test_exactly_three_tools_are_declared_as_native_functions() -> None:
    assert len(AGENT_TOOL_DEFINITIONS) == 3
    assert {
        "search_docs",
        "read_doc",
        "search_related_questions",
    } == AGENT_TOOL_NAMES
    for declaration in AGENT_TOOL_DEFINITIONS:
        assert declaration["type"] == "function"
        function = declaration["function"]
        assert function["name"] in AGENT_TOOL_NAMES
        assert function["strict"] is True
        assert function["parameters"]["additionalProperties"] is False


def _registry(calls: list[tuple[str, dict[str, Any]]]) -> AgentToolRegistry:
    def handler(name: AgentToolName):  # type: ignore[no-untyped-def]
        async def execute(arguments: ToolInput) -> dict[str, bool]:
            calls.append((name.value, arguments.model_dump()))
            return {"ok": True}

        return execute

    return AgentToolRegistry(
        {
            AgentToolName.SEARCH_DOCS: handler(AgentToolName.SEARCH_DOCS),
            AgentToolName.READ_DOC: handler(AgentToolName.READ_DOC),
            AgentToolName.SEARCH_RELATED_QUESTIONS: handler(AgentToolName.SEARCH_RELATED_QUESTIONS),
        }
    )


@pytest.mark.asyncio
async def test_allowlisted_call_is_validated_and_dispatched() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    result = await _registry(calls).execute(
        "search_docs",
        '{"query":"خطای استقرار","runtime":"python","top_k":3}',
    )

    assert result == {"ok": True}
    assert calls == [
        (
            "search_docs",
            {
                "query": "خطای استقرار",
                "service": None,
                "runtime": "python",
                "framework": None,
                "top_k": 3,
            },
        )
    ]


@pytest.mark.asyncio
async def test_non_allowlisted_capability_is_unreachable() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    with pytest.raises(RescueError) as caught:
        await _registry(calls).execute("run_shell", {"command": "whoami"})

    assert caught.value.code is ErrorCode.INVALID_REQUEST
    assert "non-allowlisted" in (caught.value.detail or "")
    assert calls == []


@pytest.mark.asyncio
async def test_extra_tool_arguments_are_rejected() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    with pytest.raises(RescueError) as caught:
        await _registry(calls).execute(
            "read_doc",
            {"document_id_or_url": "doc-id", "filesystem_path": "C:/secret"},
        )

    assert caught.value.code is ErrorCode.INVALID_REQUEST
    assert calls == []


@pytest.mark.asyncio
async def test_session_profile_is_reused_as_a_soft_retrieval_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_runtimes: list[str] = []

    async def fake_search(*args: Any, **kwargs: Any) -> list[Any]:
        seen_runtimes.append(kwargs["intent"].profile_hints["runtime"])
        return []

    monkeypatch.setattr("src.services.agent_tools.search_documentation", fake_search)
    registry = build_documentation_tool_registry(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        settings=Settings(_env_file=None),
        profile={"runtime": "python"},
    )

    await registry.execute("search_docs", {"query": "deploy"})
    registry.set_profile({"runtime": "nodejs"})
    await registry.execute("search_docs", {"query": "deploy"})

    assert seen_runtimes == ["python", "nodejs"]


def test_search_citation_uses_explicit_page_title_not_nested_breadcrumbs() -> None:
    result = RetrievalResult(
        chunk_id=uuid.uuid4(),
        index_version_id=uuid.uuid4(),
        similarity=0.8,
        text="evidence",
        metadata={
            "page_title": "استقرار برنامه NextJS در لیارا",
            "section_title": "اجرای اسکریپت start",
            "breadcrumbs": [
                "استقرار برنامه NextJS در لیارا",
                "mirror لیارا",
                "اجرای اسکریپت start",
            ],
        },
        images=[],
        source_url="https://docs.liara.ir/paas/nextjs/how-tos/deploy-app",
        heading_anchor="start-script",
        source_commit="a" * 40,
    )

    evidence = _chunk_evidence(result)

    assert evidence["citation"]["page_title"] == "استقرار برنامه NextJS در لیارا"
    assert evidence["citation"]["section_title"] == "اجرای اسکریپت start"
