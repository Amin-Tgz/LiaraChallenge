"""The chat agent's complete and immutable native-tool allowlist."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core.errors import ErrorCode, RescueError


class AgentToolName(StrEnum):
    SEARCH_DOCS = "search_docs"
    READ_DOC = "read_doc"
    SEARCH_RELATED_QUESTIONS = "search_related_questions"


class _StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchDocsInput(_StrictToolInput):
    query: str = Field(min_length=1)
    service: str | None = Field(default=None, min_length=1)
    runtime: str | None = Field(default=None, min_length=1)
    framework: str | None = Field(default=None, min_length=1)
    top_k: int | None = Field(default=None, ge=1)


class ReadDocInput(_StrictToolInput):
    document_id_or_url: str = Field(min_length=1)
    section: str | None = Field(default=None, min_length=1)


class SearchRelatedQuestionsInput(_StrictToolInput):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1)


ToolInput = SearchDocsInput | ReadDocInput | SearchRelatedQuestionsInput
ToolHandler = Callable[[ToolInput], Awaitable[Any]]

_INPUT_MODELS: Mapping[AgentToolName, type[_StrictToolInput]] = MappingProxyType(
    {
        AgentToolName.SEARCH_DOCS: SearchDocsInput,
        AgentToolName.READ_DOC: ReadDocInput,
        AgentToolName.SEARCH_RELATED_QUESTIONS: SearchRelatedQuestionsInput,
    }
)

_DESCRIPTIONS: Mapping[AgentToolName, str] = MappingProxyType(
    {
        AgentToolName.SEARCH_DOCS: (
            "Search the indexed public Liara documentation for citable evidence."
        ),
        AgentToolName.READ_DOC: (
            "Read one indexed Liara documentation page or a named section of it."
        ),
        AgentToolName.SEARCH_RELATED_QUESTIONS: (
            "Search documentation-derived related questions and their attributed answers."
        ),
    }
)


def _native_definition(name: AgentToolName) -> dict[str, Any]:
    """OpenAI-compatible native function declaration for one allowed tool."""
    return {
        "type": "function",
        "function": {
            "name": name.value,
            "description": _DESCRIPTIONS[name],
            "strict": True,
            "parameters": _INPUT_MODELS[name].model_json_schema(),
        },
    }


AGENT_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = tuple(
    _native_definition(name) for name in AgentToolName
)
AGENT_TOOL_NAMES: frozenset[str] = frozenset(name.value for name in AgentToolName)


class AgentToolRegistry:
    """Validates and dispatches only the three documentation capabilities."""

    def __init__(self, handlers: Mapping[AgentToolName, ToolHandler]) -> None:
        expected = frozenset(AgentToolName)
        provided = frozenset(handlers)
        if provided != expected:
            missing = sorted(name.value for name in expected - provided)
            extra = sorted(str(name) for name in provided - expected)
            raise ValueError(f"agent tool registry mismatch; missing={missing}, extra={extra}")
        self._handlers = MappingProxyType(dict(handlers))

    @property
    def definitions(self) -> tuple[dict[str, Any], ...]:
        return AGENT_TOOL_DEFINITIONS

    async def execute(self, name: str, arguments: str | Mapping[str, Any]) -> Any:
        """Reject an unlisted name before considering its arguments or a handler."""
        try:
            tool_name = AgentToolName(name)
        except ValueError as err:
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail=f"agent requested non-allowlisted tool {name!r}",
            ) from err

        try:
            raw = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
            parsed = _INPUT_MODELS[tool_name].model_validate(raw)
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as err:
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail=f"invalid arguments for agent tool {tool_name.value}",
            ) from err
        return await self._handlers[tool_name](parsed)
