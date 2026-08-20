"""Explicit bounded loop for the documentation-only chat agent."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models import UsageEvent
from src.db.models.enums import UsageEventType
from src.services.agent_tools import AGENT_TOOL_NAMES, AgentToolRegistry
from src.services.gateway import ChatCompletion, GatewayTelemetry

logger = get_logger(__name__)
Executor = AsyncSession | AsyncConnection


class ChatModel(Protocol):
    async def complete(
        self,
        executor: Executor,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        response_format: Mapping[str, Any] | None = None,
        reasoning_effort: str | None = None,
        telemetry: GatewayTelemetry | None = None,
    ) -> ChatCompletion: ...


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    content: str
    messages: tuple[dict[str, Any], ...]
    tool_calls: int
    rewrites: int
    total_tokens: int
    limit_reason: str | None = None
    error_code: ErrorCode | None = None


def _tool_calls(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = message.get("tool_calls") or []
    if not isinstance(raw, list):
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="model tool_calls must be an array")
    return [dict(item) for item in raw]


def _call_parts(call: Mapping[str, Any]) -> tuple[str, str, str]:
    try:
        call_id = str(call["id"])
        function = call["function"]
        name = str(function["name"])
        arguments = str(function["arguments"])
    except (KeyError, TypeError) as err:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail="model returned malformed tool call",
        ) from err
    return call_id, name, arguments


def _normalized_tool_query(arguments: str) -> str | None:
    try:
        raw = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("query"), str):
        return None
    return normalize_query(raw["query"])


class BoundedAgent:
    """Runs model/tool turns while enforcing every bound outside the prompt."""

    def __init__(
        self,
        model: ChatModel,
        tools: AgentToolRegistry,
        settings: Settings | None = None,
    ) -> None:
        self.model = model
        self.tools = tools
        self.settings = settings or get_settings()

    async def _record_limit(
        self,
        executor: Executor,
        *,
        telemetry: GatewayTelemetry,
        error_code: ErrorCode,
        limit: str,
        tool_calls: int,
        rewrites: int,
        total_tokens: int,
    ) -> None:
        try:
            await executor.execute(
                UsageEvent.__table__.insert().values(
                    event_type=UsageEventType.ERROR.value,
                    trace_id=telemetry.trace_id,
                    session_id=telemetry.session_id,
                    conversation_id=telemetry.conversation_id,
                    job_id=telemetry.job_id,
                    index_version_id=telemetry.index_version_id,
                    error_code=error_code.value,
                    question=telemetry.question,
                    total_tokens=total_tokens,
                    payload={
                        "limit": limit,
                        "tool_calls": tool_calls,
                        "rewrites": rewrites,
                    },
                )
            )
        except SQLAlchemyError as err:
            logger.warning(
                "agent limit telemetry failed",
                extra={
                    "trace_id": telemetry.trace_id,
                    "error_code": error_code.value,
                    "cause": type(err).__name__,
                },
            )

    async def _run(
        self,
        executor: Executor,
        *,
        question: str,
        messages: Sequence[Mapping[str, Any]],
        telemetry: GatewayTelemetry,
    ) -> AgentTurnResult:
        conversation = [dict(message) for message in messages]
        if not conversation:
            conversation.append({"role": "user", "content": question})
        tool_calls_used = 0
        rewrites_used = 0
        total_tokens = 0
        query_forms = {normalize_query(question)}
        limit_reason: str | None = None

        while True:
            force_final = limit_reason is not None or (
                tool_calls_used >= self.settings.agent_max_tool_calls
            )
            if force_final and limit_reason is None:
                limit_reason = "tool_calls"
            if total_tokens >= self.settings.agent_token_budget:
                await self._record_limit(
                    executor,
                    telemetry=telemetry,
                    error_code=ErrorCode.AGENT_LIMIT_REACHED,
                    limit="tokens",
                    tool_calls=tool_calls_used,
                    rewrites=rewrites_used,
                    total_tokens=total_tokens,
                )
                raise RescueError(
                    ErrorCode.AGENT_LIMIT_REACHED,
                    detail="agent token budget exhausted before another model call",
                )

            request_messages = list(conversation)
            if force_final:
                request_messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Tool access has ended at the configured limit. Answer only from "
                            "evidence already returned, or abstain if it is insufficient."
                        ),
                    }
                )
            completion = await self.model.complete(
                executor,
                messages=request_messages,
                tools=None if force_final else self.tools.definitions,
                tool_choice=None if force_final else "auto",
                telemetry=telemetry,
            )
            total_tokens += completion.total_tokens
            if total_tokens > self.settings.agent_token_budget:
                await self._record_limit(
                    executor,
                    telemetry=telemetry,
                    error_code=ErrorCode.AGENT_LIMIT_REACHED,
                    limit="tokens",
                    tool_calls=tool_calls_used,
                    rewrites=rewrites_used,
                    total_tokens=total_tokens,
                )
                raise RescueError(
                    ErrorCode.AGENT_LIMIT_REACHED,
                    detail="model response exceeded the configured agent token budget",
                )

            assistant_message = dict(completion.message)
            calls = _tool_calls(assistant_message)
            if force_final:
                content = assistant_message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RescueError(
                        ErrorCode.AGENT_LIMIT_REACHED,
                        detail=f"agent reached {limit_reason} limit without a final answer",
                    )
                conversation.append(assistant_message)
                await self._record_limit(
                    executor,
                    telemetry=telemetry,
                    error_code=ErrorCode.AGENT_LIMIT_REACHED,
                    limit=limit_reason or "tool_calls",
                    tool_calls=tool_calls_used,
                    rewrites=rewrites_used,
                    total_tokens=total_tokens,
                )
                return AgentTurnResult(
                    content=content,
                    messages=tuple(conversation),
                    tool_calls=tool_calls_used,
                    rewrites=rewrites_used,
                    total_tokens=total_tokens,
                    limit_reason=limit_reason,
                    error_code=ErrorCode.AGENT_LIMIT_REACHED,
                )

            if not calls:
                content = assistant_message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RescueError(
                        ErrorCode.INTERNAL_ERROR,
                        detail="model returned neither content nor a tool call",
                    )
                conversation.append(assistant_message)
                return AgentTurnResult(
                    content=content,
                    messages=tuple(conversation),
                    tool_calls=tool_calls_used,
                    rewrites=rewrites_used,
                    total_tokens=total_tokens,
                )

            conversation.append(assistant_message)
            for call in calls:
                call_id, name, arguments = _call_parts(call)
                if limit_reason is not None:
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": json.dumps({"error": f"agent_{limit_reason}_limit_reached"}),
                        }
                    )
                    continue
                if tool_calls_used >= self.settings.agent_max_tool_calls:
                    limit_reason = "tool_calls"
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": json.dumps({"error": "agent_tool_calls_limit_reached"}),
                        }
                    )
                    continue
                if name not in AGENT_TOOL_NAMES:
                    # The registry owns the rejection, keeping one allowlist for both
                    # declarations and execution.
                    await self.tools.execute(name, arguments)
                    raise AssertionError("unreachable after non-allowlisted tool rejection")
                query = _normalized_tool_query(arguments)
                if query and query not in query_forms:
                    if rewrites_used >= self.settings.agent_max_rewrites:
                        limit_reason = "rewrites"
                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": name,
                                "content": json.dumps({"error": "agent_rewrites_limit_reached"}),
                            }
                        )
                        continue
                    query_forms.add(query)
                    rewrites_used += 1
                output = await self.tools.execute(name, arguments)
                tool_calls_used += 1
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": json.dumps(output, ensure_ascii=False, default=str),
                    }
                )

    async def run(
        self,
        executor: Executor,
        *,
        question: str,
        messages: Sequence[Mapping[str, Any]] = (),
        telemetry: GatewayTelemetry | None = None,
    ) -> AgentTurnResult:
        """Run one turn inside the configured wall-clock deadline."""
        telemetry = telemetry or GatewayTelemetry(question=question)
        try:
            async with asyncio.timeout(self.settings.agent_timeout_seconds):
                return await self._run(
                    executor,
                    question=question,
                    messages=messages,
                    telemetry=telemetry,
                )
        except TimeoutError as err:
            await self._record_limit(
                executor,
                telemetry=telemetry,
                error_code=ErrorCode.UPSTREAM_TIMEOUT,
                limit="timeout",
                tool_calls=0,
                rewrites=0,
                total_tokens=0,
            )
            raise RescueError(
                ErrorCode.UPSTREAM_TIMEOUT,
                detail=(
                    "agent turn exceeded "
                    f"the configured {self.settings.agent_timeout_seconds:g}-second timeout"
                ),
            ) from err
