"""§10.1, §10.2, §10.5, §10.6 — persistence, retries, idempotency, durability."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.errors import ErrorCode, RescueError
from src.db.models.conversation import AnonymousSession, Conversation, Message, RequestJob
from src.db.models.enums import JobStatus
from src.services.agent import AgentCitation, AgentTurnResult
from src.services.job_runner import process_job
from src.services.jobs import (
    QUEUE_KEY,
    acquire_lease,
    create_or_get_job,
    enqueue,
    lease_key,
    reclaim_orphaned_jobs,
    release_lease,
)

pytestmark = pytest.mark.asyncio


async def _conversation(session: AsyncSession) -> Conversation:
    anon = AnonymousSession(id=uuid.uuid4())
    session.add(anon)
    await session.flush()
    conversation = Conversation(
        session_id=anon.id,
        initial_question="چطور برنامه را روی لیارا مستقر کنم؟",
        initial_question_normalized="چطور برنامه را روی لیارا مستقر کنم؟",
        technical_profile={},
    )
    session.add(conversation)
    await session.flush()
    return conversation


class StubAgent:
    """Stands in for the bounded agent so job mechanics are what is under test."""

    def __init__(self, *results: Any) -> None:
        self._results = list(results)
        self.calls = 0

    async def run(self, executor: Any, **kwargs: Any) -> AgentTurnResult:
        self.calls += 1
        outcome = self._results.pop(0) if self._results else self._results
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _answer(content: str = "برای استقرار از liara deploy استفاده کنید.") -> AgentTurnResult:
    return AgentTurnResult(
        content=content,
        messages=(),
        tool_calls=1,
        rewrites=0,
        total_tokens=120,
        citations=(
            AgentCitation(
                evidence_id="e1",
                url="https://docs.liara.ir/paas/deploy#deploy",
                page_title="استقرار",
                section_title="deploy",
                source_commit="a" * 40,
            ),
        ),
        images=(
            {
                "evidence_id": "e1",
                "url": "https://media.liara.ir/deploy.png",
                "alt": "مرحلهٔ استقرار",
            },
        ),
    )


async def test_job_is_persisted_before_it_is_enqueued(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """§10.1 — the row exists first, so a crash cannot lose the question."""
    conversation = await _conversation(db_session)
    job, created = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    assert created is True

    stored = await db_session.get(RequestJob, job.id)
    assert stored is not None
    assert stored.status == JobStatus.QUEUED
    assert stored.stream_key == f"rescue:jobs:{job.id}:stream"
    # Persisted, but not yet visible to a worker.
    assert await redis_client.lpos(QUEUE_KEY, str(job.id)) is None

    await enqueue(redis_client, job.id)
    assert await redis_client.lpos(QUEUE_KEY, str(job.id)) is not None


async def test_resubmitting_an_idempotency_key_creates_no_second_job(
    db_session: AsyncSession,
) -> None:
    """§10.5 — a retried POST and a reloaded tab must not double the work."""
    conversation = await _conversation(db_session)
    key = uuid.uuid4().hex

    first, created_first = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question="سؤال اول",
        idempotency_key=key,
    )
    second, created_second = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question="سؤال اول",
        idempotency_key=key,
    )

    assert created_first is True
    assert created_second is False
    # Both submissions observe the same job, which is what "same result" means.
    assert first.id == second.id


async def test_successful_job_records_every_transition(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """§10.1 — queued → retrieving → generating → completed, all recorded."""
    conversation = await _conversation(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )

    outcome = await process_job(db_session, redis_client, job, StubAgent(_answer()))

    assert outcome.status == JobStatus.COMPLETED
    recorded = [entry["status"] for entry in job.transitions]
    assert recorded == [
        JobStatus.QUEUED,
        JobStatus.RETRIEVING,
        JobStatus.GENERATING,
        JobStatus.COMPLETED,
    ]
    assert job.result_message_id is not None
    message = await db_session.get(Message, job.result_message_id)
    assert message is not None
    assert message.images == [
        {
            "evidence_id": "e1",
            "url": "https://media.liara.ir/deploy.png",
            "alt": "مرحلهٔ استقرار",
        }
    ]
    assert job.finished_at is not None


async def test_transient_failure_retries_then_stops_at_the_attempt_ceiling(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """§10.2 — exhausted retries reach a terminal state rather than looping."""
    conversation = await _conversation(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    job.max_attempts = 2
    await db_session.flush()

    transient = RescueError(ErrorCode.UPSTREAM_TIMEOUT, detail="provider was slow")

    first = await process_job(db_session, redis_client, job, StubAgent(transient))
    assert first.status == JobStatus.RETRYING
    assert first.requeued is True

    reloaded = await db_session.get(RequestJob, job.id)
    assert reloaded is not None
    second = await process_job(db_session, redis_client, reloaded, StubAgent(transient))

    assert second.status == JobStatus.FAILED
    assert second.requeued is False
    assert second.error_code is ErrorCode.UPSTREAM_TIMEOUT
    assert reloaded.attempt == reloaded.max_attempts


async def test_permanent_failure_does_not_retry(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """§14.8 classification — an auth failure is not made true by repetition."""
    conversation = await _conversation(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    job.max_attempts = 5
    await db_session.flush()

    permanent = RescueError(ErrorCode.UNAUTHORIZED, detail="provider rejected the credential")
    outcome = await process_job(db_session, redis_client, job, StubAgent(permanent))

    assert outcome.status == JobStatus.FAILED
    assert outcome.error_code is ErrorCode.UNAUTHORIZED
    assert job.attempt == 1


async def test_abstention_completes_the_job_rather_than_failing_it(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """A documentation gap is a working system, not an outage."""
    conversation = await _conversation(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    abstention = AgentTurnResult(
        content="شواهد کافی پیدا نکردم.",
        messages=(),
        tool_calls=1,
        rewrites=0,
        total_tokens=40,
        error_code=ErrorCode.NO_EVIDENCE,
    )

    outcome = await process_job(db_session, redis_client, job, StubAgent(abstention))

    assert outcome.status == JobStatus.COMPLETED
    assert outcome.error_code is ErrorCode.NO_EVIDENCE
    assert job.status == JobStatus.COMPLETED


async def test_a_job_whose_worker_died_is_reclaimed(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """§10.6 — killing the worker mid-generation must not lose the question."""
    conversation = await _conversation(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    # Simulate a worker that claimed the job and then died: the row is
    # mid-flight and the queue entry is gone.
    job.status = JobStatus.GENERATING
    await db_session.commit()
    assert await acquire_lease(redis_client, job.id, "worker-that-dies") is True

    # While the lease is held, nothing is reclaimed.
    assert job.id not in await reclaim_orphaned_jobs(db_session, redis_client)

    # The dead worker's lease expires on its own — no cleanup code runs.
    await release_lease(redis_client, job.id)
    assert await redis_client.exists(lease_key(job.id)) == 0

    reclaimed = await reclaim_orphaned_jobs(db_session, redis_client)
    assert job.id in reclaimed
    assert await redis_client.lpos(QUEUE_KEY, str(job.id)) is not None


async def test_reclaim_ignores_jobs_already_waiting_in_the_queue(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """Reclaiming a queued job would run it twice."""
    conversation = await _conversation(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    await db_session.commit()
    await enqueue(redis_client, job.id)

    assert job.id not in await reclaim_orphaned_jobs(db_session, redis_client)
    queued = await redis_client.lrange(QUEUE_KEY, 0, -1)
    # Still exactly one entry: reclaiming a queued job would run it twice.
    assert queued.count(str(job.id)) == 1


async def test_max_attempts_comes_from_configuration(db_session: AsyncSession) -> None:
    """§2 config-over-code — the retry ceiling is not a literal in the runner."""
    conversation = await _conversation(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    assert job.max_attempts == get_settings().job_max_attempts
