"""§10.7 — shutdown drains in-flight work instead of abandoning it."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from redis.asyncio import Redis

import src.worker as worker
from src.services.jobs import QUEUE_KEY

pytestmark = pytest.mark.asyncio


async def test_an_idle_worker_stops_promptly_when_asked(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deploy must not wait on a worker that has nothing to do."""
    stop = asyncio.Event()
    monkeypatch.setattr(worker, "reclaim_orphaned_jobs", _no_reclaim)

    loop_task = asyncio.create_task(worker._run(stop))
    await asyncio.sleep(0.1)
    stop.set()

    # Bounded by job_queue_block_seconds, not by an arbitrary sleep.
    await asyncio.wait_for(loop_task, timeout=10)
    assert loop_task.done()


async def test_a_job_already_picked_up_finishes_before_the_loop_exits(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drain: stopping mid-job completes it rather than dropping it.

    This is what keeps a redeploy from turning in-progress questions into
    failures the user has to retype.
    """
    finished: list[uuid.UUID] = []
    job_id = uuid.uuid4()

    async def slow_job(session: Any, redis: Any, claimed: uuid.UUID, **kwargs: Any) -> None:
        # Ask for shutdown while this job is still running.
        stop.set()
        await asyncio.sleep(0.3)
        finished.append(claimed)

    stop = asyncio.Event()
    monkeypatch.setattr(worker, "reclaim_orphaned_jobs", _no_reclaim)
    monkeypatch.setattr(worker, "_run_one", slow_job)

    await redis_client.lpush(QUEUE_KEY, str(job_id))
    await asyncio.wait_for(worker._run(stop), timeout=15)

    assert finished == [job_id], "shutdown abandoned a job that had already started"


async def _no_reclaim(*args: Any, **kwargs: Any) -> list[uuid.UUID]:
    """Startup reclamation is covered by its own test; keep this one focused."""
    return []
