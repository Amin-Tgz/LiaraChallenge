"""The three retrieval outcomes that must never collapse into one message."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.db.models import IndexVersion, UsageEvent
from src.services import retrieval
from src.services.retrieval import FusedRetrievalResult, RetrievalTelemetry

pytestmark = pytest.mark.asyncio


class UnusedEmbeddings:
    def embed_one(self, text: str) -> list[float]:  # pragma: no cover - patched search
        raise AssertionError(text)


def _candidate(similarity: float, index_version_id: uuid.UUID) -> FusedRetrievalResult:
    return FusedRetrievalResult(
        chunk_id=uuid.UUID(int=1),
        index_version_id=index_version_id,
        fusion_score=0.1,
        dense_rank=1,
        lexical_rank=None,
        similarity=similarity,
        lexical_score=None,
        text="evidence",
        metadata={"source_path": "src/pages/test.mdx"},
        images=[],
        source_url="https://docs.liara.ir/test",
        heading_anchor="answer",
        source_commit="a" * 40,
    )


@pytest.mark.parametrize(
    "code",
    [ErrorCode.NO_ACTIVE_INDEX, ErrorCode.RETRIEVAL_FAILED],
)
async def test_system_failures_preserve_their_own_code_and_message(
    migrated: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
    code: ErrorCode,
) -> None:
    async def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RescueError(code, detail="simulated")

    monkeypatch.setattr(retrieval, "hybrid_retrieve", fail)

    with pytest.raises(RescueError) as caught:
        await retrieval.search_documentation(
            migrated,
            "سؤال آزمایشی",
            UnusedEmbeddings(),
            telemetry=RetrievalTelemetry(trace_id=f"trace-{code.value}"),
        )

    assert caught.value.code is code
    assert caught.value.message_fa == caught.value.spec.message_fa


async def test_healthy_empty_search_has_distinct_code_and_records_gap(
    migrated: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_id = (
        await migrated.execute(select(IndexVersion.id).where(IndexVersion.is_active.is_(True)))
    ).scalar_one()

    async def below_threshold(*args, **kwargs):  # type: ignore[no-untyped-def]
        return [_candidate(0.2, active_id)]

    monkeypatch.setattr(retrieval, "hybrid_retrieve", below_threshold)
    settings = Settings(_env_file=None, retrieval_similarity_threshold=0.25)
    question = f"gap-{uuid.uuid4()}"

    with pytest.raises(RescueError) as caught:
        await retrieval.search_documentation(
            migrated,
            question,
            UnusedEmbeddings(),
            settings=settings,
            telemetry=RetrievalTelemetry(trace_id="trace-gap"),
        )

    assert caught.value.code is ErrorCode.NO_RESULTS_ABOVE_THRESHOLD
    assert caught.value.message_fa != RescueError(ErrorCode.NO_ACTIVE_INDEX).message_fa
    event = (
        await migrated.execute(select(UsageEvent).where(UsageEvent.question == question))
    ).one()
    assert event.error_code == ErrorCode.NO_RESULTS_ABOVE_THRESHOLD.value
    assert event.payload["similarity_threshold"] == pytest.approx(0.25)
    assert event.payload["top_similarity"] == pytest.approx(0.2)


async def test_a_filter_the_corpus_never_uses_is_not_reported_as_a_docs_gap(
    migrated: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fourth outcome, found by driving the Skill through a real agent.

    A hard filter on a value the index does not store removes every candidate.
    Reported as NO_RESULTS_ABOVE_THRESHOLD it reads as "the documentation has no
    answer" — which sent an agent to a confident, wrong abstention over
    documentation that plainly existed.
    """

    async def nothing(*args, **kwargs):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr(retrieval, "hybrid_retrieve", nothing)
    question = f"filter-{uuid.uuid4()}"

    with pytest.raises(RescueError) as caught:
        await retrieval.search_documentation(
            migrated,
            question,
            UnusedEmbeddings(),
            intent=retrieval.RetrievalIntent(explicit_filters={"runtime": "haskell"}),
            telemetry=RetrievalTelemetry(trace_id="trace-filter"),
        )

    assert caught.value.code is ErrorCode.NO_RESULTS_FOR_FILTER
    assert caught.value.code is not ErrorCode.NO_RESULTS_ABOVE_THRESHOLD
    # The operator detail must name the offending field and what the corpus
    # does hold, or the next person debugging this learns nothing.
    assert "runtime='haskell'" in (caught.value.detail or "")
    assert caught.value.context["filter_field"] == "runtime"
    assert "nodejs" in caught.value.context["filter_values_present"]


async def test_the_documented_runtime_alias_no_longer_empties_the_result_set(
    migrated: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`runtime="node"` is what a caller types; `nodejs` is what the index holds."""
    seen: dict[str, str] = {}

    async def capture(*args, **kwargs):  # type: ignore[no-untyped-def]
        intent = kwargs.get("intent")
        if intent is not None:
            seen.update(intent.explicit_filters)
        return []

    monkeypatch.setattr(retrieval, "hybrid_retrieve", capture)

    with pytest.raises(RescueError):
        await retrieval.search_documentation(
            migrated,
            f"alias-{uuid.uuid4()}",
            UnusedEmbeddings(),
            intent=retrieval.RetrievalIntent(explicit_filters={"runtime": "node"}),
            telemetry=RetrievalTelemetry(trace_id="trace-alias"),
        )

    # Retrieval saw the corpus's own token, so the filter can actually match.
    assert seen["runtime"] == "nodejs"
