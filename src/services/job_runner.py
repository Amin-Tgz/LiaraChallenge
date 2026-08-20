"""Worker-side processing for one answering job.

Kept separate from `src.worker` so the interesting behavior — state
transitions, retry classification, relay output — is exercisable without
starting a process or a signal handler.

A distinction this module is careful about: **an abstention is a completed job,
not a failed one.** When the agent finds insufficient evidence it returns a
result carrying `NO_EVIDENCE`; the system worked exactly as designed and the
user gets an honest answer. Only a job that could not produce any answer
reaches `failed`. Collapsing the two would make a healthy documentation gap
look like an outage on every dashboard.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError, spec_for
from src.core.logging import get_logger
from src.db.models.conversation import Conversation, Message, RequestJob
from src.db.models.enums import JobStatus, MessageRole
from src.services.agent import AgentTurnResult, BoundedAgent
from src.services.gateway import GatewayTelemetry
from src.services.jobs import (
    JobEventType,
    citations_payload,
    enqueue,
    publish,
    publish_answer,
    record_transition,
    refresh_lease,
)
from src.services.metrics import JOB_ATTEMPTS, JOB_DURATION, JOB_OUTCOMES, JOBS_IN_FLIGHT

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """What happened to one attempt, and whether another one is owed."""

    status: JobStatus
    error_code: ErrorCode | None = None
    requeued: bool = False
    message_id: uuid.UUID | None = None


async def conversation_history(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Prior user/assistant turns, newest-last, capped at the configured depth.

    Tool messages are deliberately excluded: replaying a previous turn's tool
    traffic would spend this turn's token budget on evidence it already used.
    """
    settings = settings or get_settings()
    limit = max(settings.max_history_turns, 0) * 2
    if limit == 0:
        return []

    rows = await session.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.role.in_((MessageRole.USER.value, MessageRole.ASSISTANT.value)),
        )
        .order_by(Message.ordinal.desc())
        .limit(limit)
    )
    turns = list(rows.scalars().all())
    turns.reverse()
    return [{"role": turn.role, "content": turn.content} for turn in turns]


async def next_ordinal(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    """Next turn position in a conversation. Shared so the API and the worker
    cannot drift into two different numbering schemes."""
    rows = await session.execute(
        select(Message.ordinal)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.ordinal.desc())
        .limit(1)
    )
    highest = rows.scalar_one_or_none()
    return 0 if highest is None else highest + 1


async def persist_turn(
    session: AsyncSession,
    job: RequestJob,
    result: AgentTurnResult,
) -> Message:
    """Store the assistant turn with the citations that justify it."""
    message = Message(
        conversation_id=job.conversation_id,
        ordinal=await next_ordinal(session, job.conversation_id),
        role=MessageRole.ASSISTANT.value,
        content=result.content,
        citations=citations_payload(result.citations),
        images=[],
        error_code=str(result.error_code) if result.error_code is not None else None,
        # The agent accumulates one budget figure across a turn's several
        # completions and does not carry the prompt/completion split back out.
        # Rather than invent a split, these stay zero: per-request token usage
        # and cost are recorded by the agent as `generation` usage_events, which
        # is what the dashboard and §14.7 attribution actually read.
        prompt_tokens=0,
        completion_tokens=0,
    )
    session.add(message)
    await session.flush()
    job.result_message_id = message.id
    return message


def _final_payload(result: AgentTurnResult, message_id: uuid.UUID) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message_id": str(message_id),
        "answer": result.content,
        "citations": citations_payload(result.citations),
        "needs_clarification": result.needs_clarification,
        "clarification_field": result.clarification_field,
        "tool_calls": result.tool_calls,
        "rewrites": result.rewrites,
    }
    if result.error_code is not None:
        # An abstention or a reached limit still completes; the client must be
        # able to say *why* the answer looks the way it does.
        payload["error_code"] = str(result.error_code)
        payload["message"] = spec_for(result.error_code).message_fa
    return payload


async def _lease_heartbeat(
    redis: Redis,
    job_id: uuid.UUID,
    *,
    settings: Settings,
) -> None:
    """Hold the lease for as long as this attempt is genuinely running."""
    interval = max(settings.job_lease_seconds / 3, 1.0)
    while True:
        await asyncio.sleep(interval)
        await refresh_lease(redis, job_id, settings=settings)


async def process_job(
    session: AsyncSession,
    redis: Redis,
    job: RequestJob,
    agent: BoundedAgent,
    *,
    settings: Settings | None = None,
) -> JobOutcome:
    """Run one attempt at answering `job`, recording every transition."""
    settings = settings or get_settings()
    service = settings.metrics_service_name
    started = time.perf_counter()

    job.attempt += 1
    JOB_ATTEMPTS.labels(service=service).inc()
    JOBS_IN_FLIGHT.labels(service=service).inc()

    heartbeat = asyncio.create_task(_lease_heartbeat(redis, job.id, settings=settings))
    try:
        await record_transition(session, job, JobStatus.RETRIEVING)
        await session.commit()
        await publish(
            redis,
            job.id,
            JobEventType.STATUS,
            {"status": str(JobStatus.RETRIEVING), "attempt": job.attempt},
            settings=settings,
        )

        conversation = await session.get(Conversation, job.conversation_id)
        history = await conversation_history(session, job.conversation_id, settings=settings)

        await record_transition(session, job, JobStatus.GENERATING)
        await session.commit()
        await publish(
            redis,
            job.id,
            JobEventType.STATUS,
            {"status": str(JobStatus.GENERATING), "attempt": job.attempt},
            settings=settings,
        )

        result = await agent.run(
            session,
            question=job.question,
            messages=history,
            telemetry=GatewayTelemetry(
                trace_id=job.trace_id,
                session_id=conversation.session_id if conversation is not None else None,
                conversation_id=job.conversation_id,
                job_id=job.id,
                question=job.question,
            ),
        )

        message = await persist_turn(session, job, result)
        await record_transition(session, job, JobStatus.COMPLETED, error_code=result.error_code)
        await session.commit()

        await publish_answer(redis, job.id, result.content, settings=settings)
        await publish(
            redis,
            job.id,
            JobEventType.FINAL,
            _final_payload(result, message.id),
            settings=settings,
        )
        JOB_OUTCOMES.labels(
            service=service,
            outcome="completed",
            error_code=str(result.error_code) if result.error_code else "none",
        ).inc()
        return JobOutcome(
            status=JobStatus.COMPLETED,
            error_code=result.error_code,
            message_id=message.id,
        )

    except RescueError as err:
        return await _handle_failure(
            session,
            redis,
            job,
            code=err.code,
            detail=err.detail,
            transient=err.transient,
            settings=settings,
        )
    except Exception as err:  # noqa: BLE001 — recorded with its own code, never swallowed
        logger.exception(
            "job attempt raised an unexpected error",
            extra={"job_id": str(job.id), "attempt": job.attempt},
        )
        return await _handle_failure(
            session,
            redis,
            job,
            code=ErrorCode.INTERNAL_ERROR,
            detail=type(err).__name__,
            transient=False,
            settings=settings,
        )
    finally:
        heartbeat.cancel()
        JOBS_IN_FLIGHT.labels(service=service).dec()
        JOB_DURATION.labels(service=service).observe(time.perf_counter() - started)


async def _handle_failure(
    session: AsyncSession,
    redis: Redis,
    job: RequestJob,
    *,
    code: ErrorCode,
    detail: str | None,
    transient: bool,
    settings: Settings,
) -> JobOutcome:
    """Retry only what retrying can fix, and stop for good once attempts run out.

    Retry classification comes from the taxonomy, not from this call site: a
    timeout or an unavailable provider is transient, a validation or auth
    failure is not. Retrying the latter would burn the budget re-earning the
    same rejection.
    """
    await session.rollback()
    refreshed = await session.get(RequestJob, job.id)
    job = refreshed if refreshed is not None else job

    may_retry = transient and job.attempt < job.max_attempts
    if may_retry:
        await record_transition(session, job, JobStatus.RETRYING, error_code=code, detail=detail)
        await session.commit()
        await publish(
            redis,
            job.id,
            JobEventType.STATUS,
            {
                "status": str(JobStatus.RETRYING),
                "attempt": job.attempt,
                "max_attempts": job.max_attempts,
                "error_code": str(code),
                "message": spec_for(code).message_fa,
            },
            settings=settings,
        )
        await enqueue(redis, job.id)
        logger.info(
            "job requeued after a transient failure",
            extra={"job_id": str(job.id), "attempt": job.attempt, "error_code": str(code)},
        )
        return JobOutcome(status=JobStatus.RETRYING, error_code=code, requeued=True)

    await record_transition(session, job, JobStatus.FAILED, error_code=code, detail=detail)
    await session.commit()
    await publish(
        redis,
        job.id,
        JobEventType.ERROR,
        {
            "error_code": str(code),
            "message": spec_for(code).message_fa,
            "attempts": job.attempt,
            "retryable": transient,
        },
        settings=settings,
    )
    JOB_OUTCOMES.labels(
        service=settings.metrics_service_name,
        outcome="failed",
        error_code=str(code),
    ).inc()
    logger.warning(
        "job reached a terminal failure",
        extra={
            "job_id": str(job.id),
            "attempt": job.attempt,
            "error_code": str(code),
            "cause": detail,
        },
    )
    return JobOutcome(status=JobStatus.FAILED, error_code=code)


def history_roles(history: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    """Small helper kept for assertions in tests and log context."""
    return tuple(str(turn.get("role")) for turn in history)
