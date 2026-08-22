"""Worker entry point.

Consumes queued answering jobs from Redis and drives each through the bounded
agent. The process is deliberately thin: everything worth testing lives in
`src.services.jobs` and `src.services.job_runner`, and what remains here is the
loop, the signal handling, and the drain.

Shutdown is a first-class path, not an afterthought. On SIGTERM the loop stops
taking new work but lets the job in flight finish, so a deploy does not turn
in-progress questions into failures. Anything that cannot finish keeps its
lease-free, non-terminal row and is reclaimed by the next worker to start.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.logging import (
    clear_correlation,
    configure_logging,
    get_logger,
    set_correlation,
    shutdown_telemetry_logging,
)
from src.core.tracing import configure_tracing, shutdown_tracing
from src.db.models.conversation import Conversation, RequestJob
from src.db.models.enums import TERMINAL_JOB_STATUSES, JobStatus
from src.db.session import dispose_engine, get_sessionmaker
from src.services.agent import BoundedAgent
from src.services.agent_tools import build_documentation_tool_registry
from src.services.embeddings import EmbeddingClient
from src.services.gateway import GatewayChatClient
from src.services.job_runner import process_job
from src.services.jobs import (
    QUEUE_KEY,
    acquire_lease,
    queue_depth,
    reclaim_orphaned_jobs,
    release_lease,
)
from src.services.metrics import QUEUE_DEPTH
from src.services.redis_client import close_redis, get_redis

logger = get_logger(__name__)


def worker_identity() -> str:
    """Who holds a lease. Host and PID make an abandoned lease traceable."""
    return f"{socket.gethostname()}:{os.getpid()}"


async def _claim_next(
    redis: Redis,
    *,
    settings: Settings,
) -> uuid.UUID | None:
    """Block briefly for the next job id. `None` means the timeout elapsed."""
    popped = await redis.brpop([QUEUE_KEY], timeout=int(settings.job_queue_block_seconds))
    if popped is None:
        return None
    _, raw = popped
    try:
        return uuid.UUID(raw)
    except ValueError:
        logger.warning("discarded an unparseable queue entry", extra={"entry": str(raw)})
        return None


async def _run_one(
    session: AsyncSession,
    redis: Redis,
    job_id: uuid.UUID,
    *,
    owner: str,
    settings: Settings,
) -> None:
    if not await acquire_lease(redis, job_id, owner, settings=settings):
        # Another worker already owns this job. Dropping it is correct: the
        # holder either finishes it or lets the lease lapse for reclamation.
        logger.debug("job already leased elsewhere", extra={"job_id": str(job_id)})
        return

    try:
        job = await session.get(RequestJob, job_id)
        if job is None:
            logger.warning("queued job no longer exists", extra={"job_id": str(job_id)})
            return
        if job.status in {status.value for status in TERMINAL_JOB_STATUSES}:
            # A duplicate queue entry for finished work. Not an error.
            logger.debug(
                "skipping an already-terminal job",
                extra={"job_id": str(job_id), "status": job.status},
            )
            return
        if job.attempt >= job.max_attempts and job.status == JobStatus.RETRYING:
            logger.warning(
                "job exhausted its attempts before pickup",
                extra={"job_id": str(job_id), "attempt": job.attempt},
            )

        set_correlation(trace_id=job.trace_id or uuid.uuid4().hex)
        # Loaded explicitly: `job.conversation` is a lazy relationship, and
        # touching it on an async session raises rather than emitting a query.
        conversation = await session.get(Conversation, job.conversation_id)
        profile = conversation.technical_profile if conversation is not None else None

        # GatewayChatClient is async; EmbeddingClient wraps a sync httpx client.
        # They nest rather than share one `async with` because of that.
        async with GatewayChatClient() as gateway:
            with EmbeddingClient() as embeddings:
                tools = build_documentation_tool_registry(
                    session,
                    embeddings,
                    settings=settings,
                    profile=profile,
                )
                agent = BoundedAgent(gateway, tools, settings)
                await process_job(session, redis, job, agent, settings=settings)
    finally:
        await release_lease(redis, job_id)
        clear_correlation()


async def _run(stop: asyncio.Event) -> None:
    settings = get_settings()
    redis = get_redis()
    await redis.ping()
    owner = worker_identity()
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        reclaimed = await reclaim_orphaned_jobs(session, redis)
    logger.info(
        "worker started",
        extra={
            "app_env": settings.app_env,
            "owner": owner,
            "reclaimed_jobs": len(reclaimed),
        },
    )

    while not stop.is_set():
        try:
            job_id = await _claim_next(redis, settings=settings)
        except Exception:  # noqa: BLE001 — a broker blip must not kill the worker
            logger.exception("failed to read from the job queue")
            await asyncio.sleep(settings.job_queue_block_seconds)
            continue

        QUEUE_DEPTH.labels(service=settings.metrics_service_name).set(await queue_depth(redis))
        if job_id is None:
            continue

        # Deliberately not cancelled by `stop`: a job that has started is
        # allowed to finish so a deploy drains rather than fails.
        async with sessionmaker() as session:
            try:
                await _run_one(session, redis, job_id, owner=owner, settings=settings)
            except Exception:  # noqa: BLE001 — one bad job must not stop the loop
                logger.exception("job processing raised", extra={"job_id": str(job_id)})


async def main() -> None:
    configure_logging()
    configure_tracing()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows development: fall back to KeyboardInterrupt handling.
            signal.signal(sig, lambda *_: stop.set())

    try:
        await _run(stop)
    finally:
        # Drain in-flight work, then release dependencies.
        with contextlib.suppress(Exception):
            await close_redis()
        with contextlib.suppress(Exception):
            await dispose_engine()
        logger.info("worker stopped")
        shutdown_tracing()
        shutdown_telemetry_logging()


if __name__ == "__main__":
    asyncio.run(main())
