"""RRF is deterministic and explains every contribution by rank."""

from __future__ import annotations

import uuid

import pytest

from src.core.config import Settings
from src.services.retrieval import (
    LexicalRetrievalResult,
    RetrievalResult,
    reciprocal_rank_fusion,
)


def _dense(name: str, similarity: float) -> RetrievalResult:
    chunk_id = uuid.uuid5(uuid.NAMESPACE_URL, name)
    return RetrievalResult(
        chunk_id=chunk_id,
        index_version_id=uuid.UUID(int=1),
        similarity=similarity,
        text=name,
        metadata={"source_path": name},
        images=[],
        source_url=f"https://docs.liara.ir/{name}",
        heading_anchor="section",
        source_commit="a" * 40,
    )


def _lexical(name: str, lexical_score: float) -> LexicalRetrievalResult:
    chunk_id = uuid.uuid5(uuid.NAMESPACE_URL, name)
    return LexicalRetrievalResult(
        chunk_id=chunk_id,
        index_version_id=uuid.UUID(int=1),
        lexical_score=lexical_score,
        text=name,
        metadata={"source_path": name},
        images=[],
        source_url=f"https://docs.liara.ir/{name}",
        heading_anchor="section",
        source_commit="a" * 40,
    )


def test_rrf_order_and_contributing_ranks_are_recoverable() -> None:
    dense = [_dense("a", 0.9), _dense("b", 0.8), _dense("dense-only", 0.7)]
    lexical = [_lexical("b", 0.5), _lexical("lexical-only", 0.4), _lexical("a", 0.3)]
    settings = Settings(_env_file=None, rrf_k=60)

    first = reciprocal_rank_fusion(dense, lexical, settings=settings)
    second = reciprocal_rank_fusion(dense, lexical, settings=settings)

    assert [result.chunk_id for result in first] == [result.chunk_id for result in second]
    assert [result.text for result in first[:2]] == ["b", "a"]
    by_text = {result.text: result for result in first}
    assert (by_text["b"].dense_rank, by_text["b"].lexical_rank) == (2, 1)
    assert (by_text["a"].dense_rank, by_text["a"].lexical_rank) == (1, 3)
    assert by_text["dense-only"].lexical_rank is None
    assert by_text["lexical-only"].dense_rank is None
    assert by_text["b"].fusion_score == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_weights_are_applied_from_configuration() -> None:
    dense = [_dense("dense-first", 0.9)]
    lexical = [_lexical("lexical-first", 0.5)]
    settings = Settings(
        _env_file=None,
        rrf_k=10,
        rrf_dense_weight=1.0,
        rrf_lexical_weight=2.0,
    )

    results = reciprocal_rank_fusion(dense, lexical, settings=settings)

    assert [result.text for result in results] == ["lexical-first", "dense-first"]
