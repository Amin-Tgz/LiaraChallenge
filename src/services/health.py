"""Readiness composed from the same checks the error taxonomy names.

`/health/ready` never returns a bare boolean. `active_index` is the check people
forget: without it a fresh deploy passes health checks and serves confident
empty answers.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from sqlalchemy import text

from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.session import get_sessionmaker

logger = get_logger(__name__)

_CHECK_TIMEOUT_SECONDS = 3.0


class CheckFailed(Exception):
    """A readiness check that knows exactly why it failed.

    The reason is a stable identifier, never a formatted exception name — an
    unreachable database and an un-migrated one need different operator action.
    """

    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        self.reason = reason
        super().__init__(detail or reason)


async def _timed(name: str, coro: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=_CHECK_TIMEOUT_SECONDS)
    except TimeoutError:
        return {"ok": False, "reason": "timeout"}
    except CheckFailed as err:
        logger.warning("readiness check failed", extra={"check": name, "reason": err.reason})
        return {"ok": False, "reason": err.reason}
    except Exception as err:  # dependency is down — report, never raise
        logger.warning(
            "readiness check failed",
            extra={"check": name, "reason": "unreachable", "cause": str(err)},
        )
        return {"ok": False, "reason": "unreachable"}
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {"ok": True, "latency_ms": latency_ms, **result}


async def _check_postgres() -> dict[str, Any]:
    async with get_sessionmaker()() as session:
        await session.execute(text("SELECT 1"))
    return {}


async def _check_redis() -> dict[str, Any]:
    from src.services.redis_client import get_redis

    await get_redis().ping()
    return {}


async def _check_active_index() -> dict[str, Any]:
    async with get_sessionmaker()() as session:
        exists = (
            await session.execute(text("SELECT to_regclass('public.index_versions') IS NOT NULL"))
        ).scalar()
        if not exists:
            # Distinct from "no rows": the schema itself was never applied.
            raise CheckFailed(
                "migrations_not_applied", detail="index_versions table does not exist"
            )
        row = (
            await session.execute(
                text(
                    "SELECT id, source_commit, embedding_dimensions "
                    "FROM index_versions WHERE is_active IS TRUE LIMIT 1"
                )
            )
        ).first()
    if row is None:
        # The schema is present but ingestion never activated an index. Without
        # this check a fresh deploy passes health and serves confident empty
        # answers.
        raise CheckFailed("no_active_index_version")
    return {
        "index_version": str(row[0]),
        "source_commit": row[1],
        "embedding_dimensions": row[2],
    }


async def _check_gateway() -> dict[str, Any]:
    import httpx

    settings = get_settings()
    base = settings.portkey_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{base}/health")
    if response.status_code >= 500:
        raise RuntimeError(f"gateway returned {response.status_code}")
    return {"provider": "avalai"}


async def readiness() -> dict[str, Any]:
    names = ("postgres", "redis", "active_index", "gateway")
    coros = (_check_postgres(), _check_redis(), _check_active_index(), _check_gateway())
    results = await asyncio.gather(*(_timed(n, c) for n, c in zip(names, coros, strict=True)))
    checks = dict(zip(names, results, strict=True))
    return {"ready": all(c["ok"] for c in checks.values()), "checks": checks}
