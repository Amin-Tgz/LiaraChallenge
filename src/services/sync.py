"""Operator-triggered incremental synchronization of the documentation index.

A full ingestion clones the corpus, re-parses what changed, and embeds it —
minutes at best, and an hour if the whole corpus moved. That cannot happen
inside a request, so the trigger starts the work and returns immediately, and
the operator polls for the outcome.

Two things this module exists to guarantee:

* **One run at a time, across every replica.** The lock lives in Redis, not in
  the process. Two concurrent ingestions would race to activate different index
  versions built from the same commit, and the loser's chunks would linger as
  orphans. The lock carries a TTL so a killed worker cannot wedge the system.
* **The outcome survives the request that started it.** Status is written to
  Redis, so the admin who triggered a sync can close the tab, and a different
  admin on a different replica can still read what happened.

The pipeline itself already guarantees the property that matters most: a failed
run leaves the previously active index in service, because activation is the
last step and is atomic.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.db.session import get_sessionmaker
from src.services.ingestion.pipeline import run_ingestion
from src.services.redis_client import get_redis

logger = get_logger(__name__)

#: Held for the duration of a run. Long enough for a full corpus rebuild;
#: refreshed while the run works, so the TTL only expires on a dead process.
SYNC_LOCK_KEY = "ingest:sync:lock"
SYNC_LOCK_TTL_SECONDS = 3600
SYNC_STATUS_KEY = "ingest:sync:status"
#: Outcomes stay readable well past the run, so an operator returning later
#: still learns what happened rather than finding nothing.
SYNC_STATUS_TTL_SECONDS = 86400
#: How often the running task extends its lock.
_LOCK_REFRESH_SECONDS = 60


async def _write_status(payload: dict[str, Any]) -> None:
    try:
        await get_redis().set(
            SYNC_STATUS_KEY, json.dumps(payload, ensure_ascii=False), ex=SYNC_STATUS_TTL_SECONDS
        )
    except RedisError as err:
        # Losing the status record must not fail or abort the ingestion itself.
        logger.warning("could not record sync status", extra={"cause": type(err).__name__})


async def read_status() -> dict[str, Any] | None:
    """The most recent run's status, or None if nothing has been recorded."""
    try:
        raw = await get_redis().get(SYNC_STATUS_KEY)
    except RedisError as err:
        raise RescueError(
            ErrorCode.INTERNAL_ERROR,
            detail="sync status store is unreachable",
        ) from err
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Report the absence rather than a half-parsed run.
        logger.warning("sync status record is unreadable; treating as absent")
        return None


async def _refresh_lock(run_id: str, stop: asyncio.Event) -> None:
    """Keep the lock alive while the run works, without making it immortal."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=_LOCK_REFRESH_SECONDS)
            return
        except TimeoutError:
            pass
        try:
            # Only extend a lock we still hold. If it expired and another run
            # took it, extending would give us a lock we do not own.
            if await get_redis().get(SYNC_LOCK_KEY) == run_id:
                await get_redis().expire(SYNC_LOCK_KEY, SYNC_LOCK_TTL_SECONDS)
        except RedisError as err:
            logger.warning("could not refresh sync lock", extra={"cause": type(err).__name__})


async def _run(run_id: str, *, force: bool, triggered_by: str | None) -> None:
    stop = asyncio.Event()
    refresher = asyncio.create_task(_refresh_lock(run_id, stop))
    started = datetime.now(UTC)
    try:
        report = await run_ingestion(get_sessionmaker(), force=force)
        await _write_status(
            {
                "run_id": run_id,
                "state": "completed",
                "triggered_by": triggered_by,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                # `no_change` is a first-class outcome here, not a degenerate
                # success — it is what most scheduled runs report.
                "result": report.summary(),
                "embeddings_skipped": report.embeddings_skipped,
            }
        )
        logger.info(
            "admin sync finished",
            extra={"run_id": run_id, "status": report.status, "triggered_by": triggered_by},
        )
    except RescueError as err:
        await _write_status(
            {
                "run_id": run_id,
                "state": "failed",
                "triggered_by": triggered_by,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "error_code": err.code.value,
                "message_fa": err.message_fa,
                "detail": err.detail,
                # The pipeline activates last, so a failure here means the
                # previously active index is untouched and still serving.
                "active_index_preserved": True,
            }
        )
        logger.error(
            "admin sync failed",
            extra={"run_id": run_id, "error_code": err.code.value, "cause": err.detail},
        )
    except Exception as err:  # noqa: BLE001 — the run is detached; nothing else can report it
        await _write_status(
            {
                "run_id": run_id,
                "state": "failed",
                "triggered_by": triggered_by,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "error_code": ErrorCode.INTERNAL_ERROR.value,
                # The exception type, never its message: an ingestion error can
                # carry a connection string.
                "detail": type(err).__name__,
                "active_index_preserved": True,
            }
        )
        logger.exception("admin sync raised", extra={"run_id": run_id})
    finally:
        stop.set()
        refresher.cancel()
        try:
            if await get_redis().get(SYNC_LOCK_KEY) == run_id:
                await get_redis().delete(SYNC_LOCK_KEY)
        except RedisError:
            # The TTL releases it either way.
            logger.warning("could not release sync lock; it will expire")


async def trigger_sync(
    *,
    force: bool = False,
    triggered_by: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Start a sync unless one is already running, and report which happened."""
    settings = settings or get_settings()
    run_id = uuid.uuid4().hex

    try:
        acquired = await get_redis().set(SYNC_LOCK_KEY, run_id, nx=True, ex=SYNC_LOCK_TTL_SECONDS)
    except RedisError as err:
        raise RescueError(
            ErrorCode.INTERNAL_ERROR,
            detail="cannot start a sync while the lock store is unreachable",
        ) from err

    if not acquired:
        # Not an error the operator caused; tell them what is already happening.
        current = await read_status()
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail="a synchronization is already running",
            context={"running": True, "current": current},
        )

    started = {
        "run_id": run_id,
        "state": "running",
        "triggered_by": triggered_by,
        "started_at": datetime.now(UTC).isoformat(),
        "force": force,
    }
    await _write_status(started)
    # Detached on purpose: the request returns now and the operator polls.
    task = asyncio.create_task(_run(run_id, force=force, triggered_by=triggered_by))
    # Held so the task is not garbage-collected mid-run, which asyncio permits
    # for tasks nobody references.
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    logger.info("admin sync started", extra={"run_id": run_id, "triggered_by": triggered_by})
    return started


#: Strong references to detached tasks; see `trigger_sync`.
_RUNNING: set[asyncio.Task[None]] = set()
