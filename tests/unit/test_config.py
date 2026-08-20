"""Configuration invariants that would otherwise fail silently in production."""

from __future__ import annotations

import pytest

from src.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_embedding_dimensions_must_stay_hnsw_indexable() -> None:
    # pgvector caps HNSW at 2000 dims; the model's native 3072 would silently
    # degrade every query to a sequential scan.
    with pytest.raises(ValueError, match="HNSW-indexable"):
        _settings(embedding_dimensions=3072)


def test_default_embedding_dimensions_is_1536() -> None:
    assert _settings().embedding_dimensions == 1536


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"rrf_k": 0}, "RRF_K must be positive"),
        ({"rrf_dense_weight": -1}, "RRF weights must be non-negative"),
        ({"rrf_lexical_weight": -1}, "RRF weights must be non-negative"),
        ({"retrieval_metadata_boost_weight": -0.1}, "RRF weights must be non-negative"),
        ({"retrieval_similarity_threshold": 1.1}, "cosine similarity thresholds"),
        ({"faq_similarity_threshold": -1.1}, "cosine similarity thresholds"),
    ],
)
def test_rrf_configuration_rejects_invalid_values(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _settings(**overrides)


def test_judge_must_differ_from_the_model_under_test() -> None:
    settings = _settings(llm_model="gemini-3.7-flash", eval_judge_model="gemini-3.7-flash")
    with pytest.raises(ValueError, match="must differ"):
        settings.assert_judge_differs_from_model_under_test()


def test_judge_must_be_configured() -> None:
    with pytest.raises(ValueError, match="not configured"):
        _settings(eval_judge_model="").assert_judge_differs_from_model_under_test()


def test_distinct_judge_is_accepted() -> None:
    settings = _settings(llm_model="gemini-3.7-flash", eval_judge_model="gpt-5.6-luna")
    settings.assert_judge_differs_from_model_under_test()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("*", []), ("", []), ("paas,dbaas", ["paas", "dbaas"]), (" paas , iaas ", ["paas", "iaas"])],
)
def test_ingest_scope_is_configuration_not_code(raw: str, expected: list[str]) -> None:
    assert _settings(ingest_sections=raw).ingest_section_list == expected
