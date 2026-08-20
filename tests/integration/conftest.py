"""Integration fixtures.

These tests need a real Postgres with pgvector — behavior like index planning
and unique-constraint enforcement cannot be observed against a substitute. When
no database is reachable they skip rather than fail, so the unit suite still
runs on a bare checkout.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from src.core.config import get_settings
from src.services.jobs import QUEUE_KEY
from src.services.redis_client import get_redis


@pytest_asyncio.fixture(scope="function")
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(get_settings().database_url, poolclass=None)
    try:
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as err:  # noqa: BLE001 — the reason belongs in the skip message
        await eng.dispose()
        pytest.skip(f"no database reachable at DATABASE_URL: {err}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def conn(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection whose work is always rolled back, so tests leave no rows."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest_asyncio.fixture
async def migrated(conn: AsyncConnection) -> AsyncConnection:
    """Asserts the schema is present rather than creating it.

    Alembic owns every schema change; a test that built its own tables would be
    testing something the deployment never runs.
    """
    present = (
        await conn.execute(text("SELECT to_regclass('public.document_chunks') IS NOT NULL"))
    ).scalar()
    if not present:
        pytest.skip("schema not applied — run `alembic upgrade head` against this database")
    return conn


@pytest_asyncio.fixture
async def db_session(migrated: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """An `AsyncSession` on the rolled-back connection.

    `join_transaction_mode="create_savepoint"` lets production code call
    `commit()` for real — which the job runner does at every transition — while
    the outer transaction still discards everything at the end of the test.
    """
    session = AsyncSession(
        bind=migrated,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """A Redis client scoped to a throwaway key namespace.

    Skips rather than fails when no broker is reachable, matching how the
    database fixtures behave on a bare checkout.
    """
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as err:  # noqa: BLE001 — the reason belongs in the skip message
        await client.aclose()
        pytest.skip(f"no Redis reachable at REDIS_URL: {err}")

    yield client

    # Leave the broker as we found it: these tests create real queue entries
    # and real streams, and a leaked queue entry would be picked up by a worker.
    for pattern in ("rescue:jobs:*",):
        async for key in client.scan_iter(match=pattern):
            await client.delete(key)
    await client.delete(QUEUE_KEY)
    await client.aclose()


@pytest_asyncio.fixture(autouse=True)
async def isolated_app_redis() -> AsyncIterator[None]:
    """Give each test its own application Redis client.

    `get_redis` memoizes one client for the process, which is right in
    production — a single event loop runs for the lifetime of the app — but
    across tests it would hand loop N+1 a connection bound to loop N, which
    fails as "Event loop is closed" inside the first command.
    """
    get_redis.cache_clear()
    yield
    if get_redis.cache_info().currsize:
        with contextlib.suppress(Exception):
            await get_redis().aclose()
    get_redis.cache_clear()
