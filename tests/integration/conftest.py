"""Integration fixtures.

These tests need a real Postgres with pgvector — behavior like index planning
and unique-constraint enforcement cannot be observed against a substitute. When
no database is reachable they skip rather than fail, so the unit suite still
runs on a bare checkout.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from src.core.config import get_settings


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
