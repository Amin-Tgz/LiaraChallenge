"""Retrieval chooses error codes from causes, never from an empty list alone."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.services.retrieval import dense_retrieve_by_vector

pytestmark = pytest.mark.asyncio


class EmptyResult:
    def one_or_none(self):  # type: ignore[no-untyped-def]
        return None


class NoActiveIndexExecutor:
    async def execute(self, statement):  # type: ignore[no-untyped-def]
        return EmptyResult()


class BrokenDatabaseExecutor:
    async def execute(self, statement):  # type: ignore[no-untyped-def]
        raise SQLAlchemyError("simulated pgvector failure")


@pytest.mark.parametrize(
    ("executor", "expected"),
    [
        (NoActiveIndexExecutor(), ErrorCode.NO_ACTIVE_INDEX),
        (BrokenDatabaseExecutor(), ErrorCode.RETRIEVAL_FAILED),
    ],
)
async def test_dense_path_selects_code_from_the_actual_cause(
    executor: object,
    expected: ErrorCode,
) -> None:
    settings = Settings(_env_file=None)

    with pytest.raises(RescueError) as caught:
        await dense_retrieve_by_vector(  # type: ignore[arg-type]
            executor,
            [0.0] * settings.embedding_dimensions,
            settings=settings,
        )

    assert caught.value.code is expected
