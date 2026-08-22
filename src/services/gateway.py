"""OpenAI-compatible chat completions through Portkey with provider fallback.

The gateway is the only network destination used here.  Providers are selected
with Portkey's OpenAI-compatible routing headers, which keeps credentials on the
server and lets the secondary provider be a different vendor entirely.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.tracing import SpanRecorder, opik_span
from src.db.models import UsageEvent
from src.db.models.enums import UsageEventType
from src.services.embeddings import CUSTOM_HOST_HEADER, PROVIDER_HEADER, PROVIDER_PROTOCOL

logger = get_logger(__name__)
Executor = AsyncSession | AsyncConnection

_TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class GatewayTelemetry:
    """Correlation data attached to generation and fallback events."""

    trace_id: str | None = None
    session_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    index_version_id: uuid.UUID | None = None
    question: str | None = None


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    """The provider message plus attributable usage for one completion."""

    message: dict[str, Any]
    finish_reason: str | None
    model: str
    provider: str
    fallback_used: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class _Provider:
    name: str
    base_url: str
    api_key: str
    model: str


class _ProviderUnavailable(Exception):
    """Internal, credential-free signal that trying another provider is safe."""

    def __init__(self, cause: str, status_code: int | None = None) -> None:
        super().__init__(cause)
        self.cause = cause
        self.status_code = status_code


class GatewayChatClient:
    """Chat client with explicit primary-to-secondary failover in application code."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or httpx.AsyncClient(timeout=self.settings.agent_timeout_seconds)
        self._owns_client = client is None

    async def __aenter__(self) -> GatewayChatClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _primary(self) -> _Provider:
        return _Provider(
            name="primary",
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            model=self.settings.llm_model,
        )

    def _fallback(self) -> _Provider | None:
        values = (
            self.settings.portkey_fallback_base_url,
            self.settings.portkey_fallback_api_key,
            self.settings.portkey_fallback_model,
        )
        if not all(values):
            return None
        return _Provider(
            name="fallback",
            base_url=self.settings.portkey_fallback_base_url,
            api_key=self.settings.portkey_fallback_api_key,
            model=self.settings.portkey_fallback_model,
        )

    @staticmethod
    def _headers(provider: _Provider) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            PROVIDER_HEADER: PROVIDER_PROTOCOL,
            CUSTOM_HOST_HEADER: provider.base_url.rstrip("/"),
        }

    async def _request(
        self,
        provider: _Provider,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str | None, int, int, int]:
        url = f"{self.settings.portkey_base_url.rstrip('/')}/v1/chat/completions"
        provider_payload = {**payload, "model": provider.model}
        with opik_span(f"chat.attempt.{provider.name}") as attempt:
            # Only the model name and the shape of the request: headers carry
            # the provider credential and must never reach a span.
            attempt.metadata(provider=provider.name, model=provider.model)
            return await self._attempt(attempt, url, provider, provider_payload)

    async def _attempt(
        self,
        attempt: SpanRecorder,
        url: str,
        provider: _Provider,
        provider_payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str | None, int, int, int]:
        try:
            response = await self.client.post(
                url,
                headers=self._headers(provider),
                json=provider_payload,
            )
        except httpx.TimeoutException as err:
            raise _ProviderUnavailable("timeout") from err
        except httpx.HTTPError as err:
            raise _ProviderUnavailable("transport_error") from err

        if response.status_code in {401, 403}:
            raise RescueError(
                ErrorCode.UNAUTHORIZED,
                detail=f"{provider.name} provider rejected the chat credential",
            )
        if response.status_code in _TRANSIENT_STATUS:
            raise _ProviderUnavailable("transient_http_status", response.status_code)
        if response.status_code >= 400:
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail=(
                    f"{provider.name} provider rejected the chat request "
                    f"({response.status_code})"
                ),
            )

        try:
            body = response.json()
            choice = body["choices"][0]
            message = dict(choice["message"])
            finish_reason = choice.get("finish_reason")
            usage = body.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
            attempt.metadata(status_code=response.status_code, finish_reason=finish_reason)
            attempt.usage(
                model=provider.model,
                provider=provider.name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        except (KeyError, IndexError, TypeError, ValueError) as err:
            raise RescueError(
                ErrorCode.INTERNAL_ERROR,
                detail=f"{provider.name} provider returned an unreadable chat response",
            ) from err
        return message, finish_reason, prompt_tokens, completion_tokens, total_tokens

    async def _record_fallback(
        self,
        executor: Executor,
        *,
        completion: ChatCompletion,
        telemetry: GatewayTelemetry,
        primary_failure: _ProviderUnavailable,
    ) -> None:
        """Best-effort telemetry; a metrics write must never fail the answer."""
        try:
            await executor.execute(
                UsageEvent.__table__.insert().values(
                    event_type=UsageEventType.PROVIDER_FALLBACK.value,
                    trace_id=telemetry.trace_id,
                    session_id=telemetry.session_id,
                    conversation_id=telemetry.conversation_id,
                    job_id=telemetry.job_id,
                    index_version_id=telemetry.index_version_id,
                    provider=completion.provider,
                    model=completion.model,
                    fallback_used=True,
                    prompt_tokens=completion.prompt_tokens,
                    completion_tokens=completion.completion_tokens,
                    total_tokens=completion.total_tokens,
                    latency_ms=completion.latency_ms,
                    question=telemetry.question,
                    payload={
                        "primary_failure": primary_failure.cause,
                        "primary_status_code": primary_failure.status_code,
                    },
                )
            )
        except SQLAlchemyError as err:
            logger.warning(
                "provider fallback telemetry failed",
                extra={
                    "trace_id": telemetry.trace_id,
                    "cause": type(err).__name__,
                },
            )

    async def complete(
        self,
        executor: Executor,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        response_format: Mapping[str, Any] | None = None,
        reasoning_effort: str | None = None,
        max_completion_tokens: int | None = None,
        telemetry: GatewayTelemetry | None = None,
    ) -> ChatCompletion:
        """Return a completion, failing over only after a transient primary failure."""
        with opik_span("chat.completion", kind="llm") as span:
            span.metadata(
                message_count=len(messages),
                tool_count=len(tools) if tools else 0,
                reasoning_effort=reasoning_effort,
                max_completion_tokens=max_completion_tokens,
                structured_output=response_format is not None,
                trace_id=telemetry.trace_id if telemetry else None,
            )
            span.content(messages=[dict(message) for message in messages])
            completion = await self._complete(
                executor,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
                reasoning_effort=reasoning_effort,
                max_completion_tokens=max_completion_tokens,
                telemetry=telemetry,
            )
            span.metadata(
                fallback_used=completion.fallback_used,
                finish_reason=completion.finish_reason,
                latency_ms=completion.latency_ms,
            )
            span.usage(
                model=completion.model,
                provider=completion.provider,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                total_tokens=completion.total_tokens,
            )
            span.content_output(message=completion.message)
            return completion

    async def _complete(
        self,
        executor: Executor,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        response_format: Mapping[str, Any] | None = None,
        reasoning_effort: str | None = None,
        max_completion_tokens: int | None = None,
        telemetry: GatewayTelemetry | None = None,
    ) -> ChatCompletion:
        if not messages:
            raise RescueError(ErrorCode.INVALID_REQUEST, detail="chat messages cannot be empty")
        payload: dict[str, Any] = {"messages": [dict(message) for message in messages]}
        if max_completion_tokens is not None:
            payload["max_completion_tokens"] = max_completion_tokens
        if tools is not None:
            payload["tools"] = [dict(tool) for tool in tools]
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if response_format is not None:
            payload["response_format"] = dict(response_format)
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort

        started = time.perf_counter()
        try:
            result = await self._request(self._primary(), payload)
        except _ProviderUnavailable as primary_failure:
            fallback = self._fallback()
            if fallback is None:
                raise RescueError(
                    ErrorCode.ALL_PROVIDERS_UNAVAILABLE,
                    detail=(
                        "primary chat provider unavailable and no complete fallback is configured"
                    ),
                ) from primary_failure
            try:
                result = await self._request(fallback, payload)
            except _ProviderUnavailable as fallback_failure:
                raise RescueError(
                    ErrorCode.ALL_PROVIDERS_UNAVAILABLE,
                    detail="primary and fallback chat providers are unavailable",
                ) from fallback_failure
            message, finish_reason, prompt_tokens, completion_tokens, total_tokens = result
            completion = ChatCompletion(
                message=message,
                finish_reason=finish_reason,
                model=fallback.model,
                provider=fallback.name,
                fallback_used=True,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            telemetry = telemetry or GatewayTelemetry()
            await self._record_fallback(
                executor,
                completion=completion,
                telemetry=telemetry,
                primary_failure=primary_failure,
            )
            logger.warning(
                "chat provider fallback used",
                extra={
                    "trace_id": telemetry.trace_id,
                    "provider": fallback.name,
                    "model": fallback.model,
                    "primary_failure": primary_failure.cause,
                },
            )
            return completion

        message, finish_reason, prompt_tokens, completion_tokens, total_tokens = result
        primary = self._primary()
        return ChatCompletion(
            message=message,
            finish_reason=finish_reason,
            model=primary.model,
            provider=primary.name,
            fallback_used=False,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
