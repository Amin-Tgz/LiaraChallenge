"""Durable answering jobs: persistence, queue, lease, and the SSE relay.

Three invariants hold this together, and each exists because of a specific way
the naive version loses a user's question:

1. **The job is persisted before it is enqueued.** A crash between the two
   leaves a row an operator can see and a reaper can retry. Enqueueing first
   would lose the question entirely if the process died before the insert.
2. **A worker holds a lease while it works.** The lease expires on its own, so a
   worker killed mid-generation releases its claim without having to run any
   cleanup code. `reclaim_orphaned_jobs` returns those jobs to the queue.
3. **Delivered content lives in a Redis Stream, not in the connection.** The
   stream's entry ids are the offsets an SSE client reconnects from, so a
   dropped connection resumes rather than restarts, and a reload does not
   re-run generation.

The relay carries *validated* answer text, not raw model tokens. The bounded
agent's final response is a JSON structure whose citations must be checked
before any of it is shown — streaming the model's raw output would put
unvalidated, possibly uncited text on screen, which the grounding rule forbids.
So the worker validates first, then relays the answer progressively. See
`openspec/changes/add-docs-rescue-assistant/design.md`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models.conversation import RequestJob
from src.db.models.enums import TERMINAL_JOB_STATUSES, JobStatus

logger = get_logger(__name__)

#: Single work queue. LPUSH to enqueue, BRPOP to consume, so ordering is FIFO.
QUEUE_KEY = "rescue:jobs:queue"

#: Statuses a job can sit in while work is still owed on it.
ACTIVE_JOB_STATUSES: tuple[str, ...] = tuple(
    status.value for status in JobStatus if status not in TERMINAL_JOB_STATUSES
)


class JobEventType(StrEnum):
    """What a relay entry carries. The SSE `event:` field uses these names."""

    #: A job state change, so the UI can name what is happening in plain language.
    STATUS = "status"
    #: A chunk of validated answer text.
    DELTA = "delta"
    #: Terminal success: the complete answer plus its citations.
    FINAL = "final"
    #: Terminal failure, carrying the error code that names its own cause.
    ERROR = "error"


def stream_key(job_id: uuid.UUID) -> str:
    return f"rescue:jobs:{job_id}:stream"


def lease_key(job_id: uuid.UUID) -> str:
    return f"rescue:jobs:{job_id}:lease"


@dataclass(frozen=True, slots=True)
class RelayEvent:
    """One entry on a job's stream. `offset` is what a client resumes from."""

    offset: str
    event: JobEventType
    data: dict[str, Any]


async def create_or_get_job(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    question: str,
    idempotency_key: str,
    trace_id: str | None = None,
    settings: Settings | None = None,
) -> tuple[RequestJob, bool]:
    """Persist a job, or return the one this key already created.

    Returns ``(job, created)``. Resubmitting a key never creates a second job,
    which is what makes a retried POST and a reloaded tab safe.
    """
    settings = settings or get_settings()

    existing = await _by_idempotency_key(session, idempotency_key)
    if existing is not None:
        return existing, False

    job = RequestJob(
        conversation_id=conversation_id,
        idempotency_key=idempotency_key,
        question=question,
        status=JobStatus.QUEUED,
        max_attempts=settings.job_max_attempts,
        trace_id=trace_id,
        transitions=[_transition_record(JobStatus.QUEUED)],
    )
    job.stream_key = None
    session.add(job)
    try:
        # A savepoint, so losing the race leaves the outer transaction usable.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        # Another request inserted the same key first. Its job is the job.
        concurrent = await _by_idempotency_key(session, idempotency_key)
        if concurrent is None:  # pragma: no cover — the constraint guarantees a row
            raise
        return concurrent, False

    job.stream_key = stream_key(job.id)
    await session.flush()
    return job, True


async def _by_idempotency_key(session: AsyncSession, key: str) -> RequestJob | None:
    result = await session.execute(
        select(RequestJob).where(RequestJob.idempotency_key == key).limit(1)
    )
    return result.scalar_one_or_none()


def _transition_record(
    status: JobStatus,
    *,
    error_code: ErrorCode | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "status": str(status),
        "at": datetime.now(UTC).isoformat(),
    }
    if error_code is not None:
        record["error_code"] = str(error_code)
    if detail is not None:
        record["detail"] = detail
    return record


async def record_transition(
    session: AsyncSession,
    job: RequestJob,
    status: JobStatus,
    *,
    error_code: ErrorCode | None = None,
    detail: str | None = None,
) -> None:
    """Move a job to `status`, appending to its append-only history.

    The history is what makes a job's life reconstructable without log
    archaeology, so every transition is recorded even when the status repeats.
    """
    job.status = status
    job.error_code = str(error_code) if error_code is not None else None
    # Reassign rather than mutate: SQLAlchemy does not track in-place edits of a
    # JSONB list, and a silently undetected change is worse than a verbose one.
    job.transitions = [
        *(job.transitions or []),
        _transition_record(status, error_code=error_code, detail=detail),
    ]

    now = datetime.now(UTC)
    if status is JobStatus.RETRIEVING and job.started_at is None:
        job.started_at = now
    if status in TERMINAL_JOB_STATUSES:
        job.finished_at = now
    await session.flush()


async def enqueue(redis: Redis, job_id: uuid.UUID) -> None:
    """Make a persisted job visible to workers. Never call this before the insert."""
    await redis.lpush(QUEUE_KEY, str(job_id))


async def queue_depth(redis: Redis) -> int:
    return int(await redis.llen(QUEUE_KEY))


async def publish(
    redis: Redis,
    job_id: uuid.UUID,
    event: JobEventType,
    data: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> str:
    """Append one entry to a job's relay stream and return its offset."""
    settings = settings or get_settings()
    key = stream_key(job_id)
    offset = await redis.xadd(
        key,
        {"event": str(event), "data": json.dumps(data, ensure_ascii=False, default=str)},
    )
    # Retention is bounded in time, not entries: a client that reconnects after
    # a reload needs the whole answer, not the tail of it.
    await redis.expire(key, settings.job_stream_ttl_seconds)
    return str(offset)


async def publish_answer(
    redis: Redis,
    job_id: uuid.UUID,
    answer: str,
    *,
    settings: Settings | None = None,
) -> None:
    """Relay a validated answer as ordered chunks.

    Chunking is a delivery concern only. The text is already complete and
    already checked; splitting it just lets the UI render progressively instead
    of blanking until the whole answer lands.
    """
    settings = settings or get_settings()
    size = settings.job_stream_chunk_chars
    for start in range(0, len(answer), size):
        await publish(
            redis,
            job_id,
            JobEventType.DELTA,
            {"text": answer[start : start + size]},
            settings=settings,
        )


async def read_relay(
    redis: Redis,
    job_id: uuid.UUID,
    *,
    last_offset: str | None = None,
    block_ms: int = 0,
) -> list[RelayEvent]:
    """Read entries after `last_offset`, blocking up to `block_ms` for new ones.

    `last_offset=None` means "from the beginning", which is what makes a client
    that reconnects without a `Last-Event-ID` receive the answer so far rather
    than only what happens next.
    """
    start = last_offset or "0-0"
    response = await redis.xread({stream_key(job_id): start}, count=200, block=block_ms or None)
    if not response:
        return []

    events: list[RelayEvent] = []
    for _, entries in response:
        for offset, fields in entries:
            try:
                event = JobEventType(fields["event"])
                data = json.loads(fields["data"])
            except (KeyError, ValueError) as err:  # pragma: no cover — we write both fields
                logger.warning(
                    "unreadable relay entry skipped",
                    extra={"job_id": str(job_id), "offset": str(offset), "cause": str(err)},
                )
                continue
            events.append(RelayEvent(offset=str(offset), event=event, data=data))
    return events


async def acquire_lease(
    redis: Redis,
    job_id: uuid.UUID,
    owner: str,
    *,
    settings: Settings | None = None,
) -> bool:
    """Claim a job. Fails if another worker already holds the lease."""
    settings = settings or get_settings()
    acquired = await redis.set(
        lease_key(job_id),
        owner,
        nx=True,
        ex=int(settings.job_lease_seconds),
    )
    return bool(acquired)


async def refresh_lease(
    redis: Redis,
    job_id: uuid.UUID,
    *,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    await redis.expire(lease_key(job_id), int(settings.job_lease_seconds))


async def release_lease(redis: Redis, job_id: uuid.UUID) -> None:
    await redis.delete(lease_key(job_id))


async def reclaim_orphaned_jobs(session: AsyncSession, redis: Redis) -> list[uuid.UUID]:
    """Return jobs whose worker died back to the queue.

    A job is orphaned when it is non-terminal, no worker holds its lease, and it
    is not already waiting in the queue. This is the mechanism behind "killing
    the worker mid-generation loses no question": no shutdown hook has to run,
    the lease simply stops being renewed.
    """
    rows = await session.execute(
        select(RequestJob.id).where(RequestJob.status.in_(ACTIVE_JOB_STATUSES))
    )
    reclaimed: list[uuid.UUID] = []
    for (job_id,) in rows.all():
        if await redis.exists(lease_key(job_id)):
            continue
        if await redis.lpos(QUEUE_KEY, str(job_id)) is not None:
            continue
        await enqueue(redis, job_id)
        reclaimed.append(job_id)

    if reclaimed:
        logger.info(
            "reclaimed orphaned jobs",
            extra={"count": len(reclaimed), "job_ids": [str(j) for j in reclaimed]},
        )
    return reclaimed


async def load_job(session: AsyncSession, job_id: uuid.UUID) -> RequestJob | None:
    return await session.get(RequestJob, job_id)


def normalized_question(question: str) -> str:
    """The same normalizer used at index time. Never a second implementation."""
    return normalize_query(question)


def citations_payload(citations: Sequence[Any]) -> list[dict[str, Any]]:
    """Serialize agent citations for storage and for the wire, in one shape."""
    return [
        {
            "evidence_id": citation.evidence_id,
            "url": citation.url,
            "page_title": citation.page_title,
            "section_title": citation.section_title,
            "source_commit": citation.source_commit,
        }
        for citation in citations
    ]
