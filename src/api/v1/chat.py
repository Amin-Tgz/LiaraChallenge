"""Chat surface: conversations, jobs, and the server-sent-event relay.

The shape of these endpoints follows one rule from the rescue-flow spec: **the
question is persisted before anything slow happens.** A reload, a dropped
connection, or a worker restart is an ordinary event, and none of them may cost
the user the thing they typed.

Generation itself is never done inside a request. The API writes a job and
returns; a worker answers it; the browser follows `/events` to watch. That is
why a reload during generation restores state instead of starting over.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError, spec_for
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models.conversation import AnonymousSession, Conversation, Message, RequestJob
from src.db.models.enums import TERMINAL_JOB_STATUSES, MessageRole
from src.db.session import get_session, get_sessionmaker
from src.services.job_runner import next_ordinal
from src.services.jobs import (
    JobEventType,
    RelayEvent,
    create_or_get_job,
    enqueue,
    read_relay,
)
from src.services.metrics import SSE_CLIENTS
from src.services.redis_client import get_redis
from src.services.sessions import resolve_session

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# --- Wire models ----------------------------------------------------------


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    #: Supplied by the client so a retried POST is provably the same request.
    idempotency_key: str | None = Field(default=None, max_length=128)


class CitationOut(BaseModel):
    evidence_id: str
    url: str
    page_title: str | None = None
    section_title: str | None = None
    source_commit: str | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    role: str
    content: str
    citations: list[CitationOut] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None


class JobOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    status: str
    attempt: int
    max_attempts: int
    error_code: str | None = None
    #: Persian, and specific to the cause. Never a generic failure line.
    message: str | None = None
    result_message_id: uuid.UUID | None = None


class AskResponse(BaseModel):
    conversation_id: uuid.UUID
    job: JobOut
    #: False when this key had already created the job, so a client can tell a
    #: fresh submission from a replayed one.
    created: bool


class ConversationSummary(BaseModel):
    id: uuid.UUID
    initial_question: str
    title: str | None
    rescue_tool: str | None
    message_count: int


class ConversationDetail(BaseModel):
    id: uuid.UUID
    initial_question: str
    title: str | None
    technical_profile: dict[str, Any]
    rescue_tool: str | None
    messages: list[MessageOut]
    jobs: list[JobOut]


# --- Helpers --------------------------------------------------------------


def _job_out(job: RequestJob) -> JobOut:
    code = ErrorCode(job.error_code) if job.error_code else None
    return JobOut(
        id=job.id,
        conversation_id=job.conversation_id,
        status=job.status,
        attempt=job.attempt,
        max_attempts=job.max_attempts,
        error_code=job.error_code,
        # The message always names the cause, so the UI never has to invent one.
        message=spec_for(code).message_fa if code is not None else None,
        result_message_id=job.result_message_id,
    )


def _message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        ordinal=message.ordinal,
        role=message.role,
        content=message.content,
        citations=[CitationOut(**citation) for citation in (message.citations or [])],
        images=list(message.images or []),
        error_code=message.error_code,
    )


def _validate_question(question: str, *, settings: Settings) -> str:
    text = question.strip()
    if not text:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="question field was empty")
    if len(text) > settings.max_question_chars:
        raise RescueError(
            ErrorCode.INPUT_TOO_LARGE,
            detail=(
                f"question is {len(text)} characters; the configured limit is "
                f"{settings.max_question_chars}"
            ),
            context={"limit": settings.max_question_chars, "received": len(text)},
        )
    return text


async def _owned_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    session: AnonymousSession,
) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    # A conversation belonging to someone else is reported exactly as a missing
    # one, so the endpoint cannot be used to probe for existence.
    if conversation is None or conversation.session_id != session.id:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail="conversation does not exist for this session",
        )
    return conversation


async def _start_job(
    db: AsyncSession,
    request: Request,
    conversation: Conversation,
    question: str,
    idempotency_key: str | None,
) -> tuple[RequestJob, bool]:
    """Persist the user's turn and its job, then enqueue. Always in that order."""
    key = idempotency_key or uuid.uuid4().hex
    job, created = await create_or_get_job(
        db,
        conversation_id=conversation.id,
        question=question,
        idempotency_key=key,
        trace_id=request.headers.get("x-request-id"),
    )
    if not created:
        # A replay. The first submission already recorded the turn and queued
        # the work; doing either again would double both.
        return job, False

    db.add(
        Message(
            conversation_id=conversation.id,
            ordinal=await next_ordinal(db, conversation.id),
            role=MessageRole.USER.value,
            content=question,
            citations=[],
            images=[],
        )
    )
    await db.flush()
    # Commit before enqueueing: a worker must never find a job id whose row is
    # not yet visible.
    await db.commit()
    await enqueue(get_redis(), job.id)
    return job, True


# --- Endpoints ------------------------------------------------------------


@router.post("/conversations", response_model=AskResponse)
async def start_conversation(
    payload: AskRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AskResponse:
    """Open a rescue attempt from the landing question."""
    settings = get_settings()
    question = _validate_question(payload.question, settings=settings)
    session = await resolve_session(db, request, response, settings=settings)

    conversation = Conversation(
        session_id=session.id,
        initial_question=question,
        initial_question_normalized=normalize_query(question),
        technical_profile={},
    )
    db.add(conversation)
    await db.flush()

    job, created = await _start_job(db, request, conversation, question, payload.idempotency_key)
    return AskResponse(conversation_id=conversation.id, job=_job_out(job), created=created)


@router.post("/conversations/{conversation_id}/messages", response_model=AskResponse)
async def continue_conversation(
    conversation_id: uuid.UUID,
    payload: AskRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AskResponse:
    """Ask a follow-up inside an existing conversation."""
    settings = get_settings()
    question = _validate_question(payload.question, settings=settings)
    session = await resolve_session(db, request, response, settings=settings)
    conversation = await _owned_conversation(db, conversation_id, session)

    job, created = await _start_job(db, request, conversation, question, payload.idempotency_key)
    return AskResponse(conversation_id=conversation.id, job=_job_out(job), created=created)


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[ConversationSummary]:
    """Everything this browser has asked, so a reopened tab restores its history."""
    session = await resolve_session(db, request, response)
    rows = await db.execute(
        select(Conversation)
        .where(Conversation.session_id == session.id)
        .order_by(Conversation.last_activity_at.desc())
    )
    conversations = list(rows.scalars().all())
    if not conversations:
        return []

    counts = dict(
        (
            await db.execute(
                select(Message.conversation_id, func.count(Message.id))
                .where(Message.conversation_id.in_([c.id for c in conversations]))
                .group_by(Message.conversation_id)
            )
        ).all()
    )
    return [
        ConversationSummary(
            id=conversation.id,
            initial_question=conversation.initial_question,
            title=conversation.title,
            rescue_tool=conversation.rescue_tool,
            message_count=int(counts.get(conversation.id, 0)),
        )
        for conversation in conversations
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationDetail:
    """Full transcript and job state — the reload path."""
    session = await resolve_session(db, request, response)
    conversation = await _owned_conversation(db, conversation_id, session)

    messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.ordinal)
            )
        )
        .scalars()
        .all()
    )
    jobs = (
        (
            await db.execute(
                select(RequestJob)
                .where(RequestJob.conversation_id == conversation.id)
                .order_by(RequestJob.created_at)
            )
        )
        .scalars()
        .all()
    )
    return ConversationDetail(
        id=conversation.id,
        initial_question=conversation.initial_question,
        title=conversation.title,
        technical_profile=dict(conversation.technical_profile or {}),
        rescue_tool=conversation.rescue_tool,
        messages=[_message_out(message) for message in messages],
        jobs=[_job_out(job) for job in jobs],
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> JobOut:
    session = await resolve_session(db, request, response)
    job = await db.get(RequestJob, job_id)
    if job is None:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="no such job")
    await _owned_conversation(db, job.conversation_id, session)
    return _job_out(job)


def _sse(event: RelayEvent) -> str:
    """One SSE frame. The `id:` is the offset a reconnecting client resumes at."""
    payload = json.dumps(event.data, ensure_ascii=False)
    return f"id: {event.offset}\nevent: {event.event}\ndata: {payload}\n\n"


@router.get("/jobs/{job_id}/events")
async def stream_job(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Follow a job to completion, resuming from `Last-Event-ID` if reconnecting.

    Omitting the header replays the job from its first entry, which is what
    makes opening this endpoint after a reload show the answer produced so far
    rather than only what happens next.
    """
    settings = get_settings()
    session = await resolve_session(db, request, response)
    job = await db.get(RequestJob, job_id)
    if job is None:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="no such job")
    await _owned_conversation(db, job.conversation_id, session)
    already_terminal = job.status in {status.value for status in TERMINAL_JOB_STATUSES}

    async def publish_stream() -> AsyncIterator[str]:
        redis = get_redis()
        service = settings.metrics_service_name
        SSE_CLIENTS.labels(service=service).inc()
        offset = last_event_id
        delivered = offset
        block_ms = int(settings.sse_keepalive_seconds * 1000)
        try:
            while True:
                if await request.is_disconnected():
                    break
                events = await read_relay(redis, job_id, last_offset=offset, block_ms=block_ms)
                if not events:
                    # A comment frame: keeps proxies from closing a quiet
                    # connection while the model is still thinking.
                    yield ": keepalive\n\n"
                    if already_terminal and offset is None:
                        # Terminal before we started and nothing was retained —
                        # the stream has expired, so say so rather than hang.
                        break
                    continue

                for event in events:
                    offset = event.offset
                    delivered = event.offset
                    yield _sse(event)
                    if event.event in (JobEventType.FINAL, JobEventType.ERROR):
                        return
        except asyncio.CancelledError:  # pragma: no cover — client went away
            raise
        finally:
            SSE_CLIENTS.labels(service=service).dec()
            if delivered:
                await _remember_offset(job_id, delivered)

    return StreamingResponse(
        publish_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Liara's router buffers by default; without this the client sees
            # nothing until the response ends, which defeats the whole endpoint.
            "X-Accel-Buffering": "no",
            **{k: v for k, v in response.headers.items() if k.lower() == "set-cookie"},
        },
    )


async def _remember_offset(job_id: uuid.UUID, offset: str) -> None:
    """Record how far this client got.

    Uses its own session: the request-scoped one is gone by the time a streaming
    response finishes. Failure here must never surface — the client already has
    the content, and the column is an operator aid, not a correctness input.
    """
    try:
        async with get_sessionmaker()() as db:
            job = await db.get(RequestJob, job_id)
            if job is not None:
                job.last_delivered_offset = offset
                await db.commit()
    except Exception as err:  # noqa: BLE001 — telemetry must not fail a request
        logger.warning(
            "could not record the delivered stream offset",
            extra={"job_id": str(job_id), "cause": type(err).__name__},
        )


__all__ = ["router"]
