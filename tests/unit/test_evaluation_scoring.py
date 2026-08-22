"""Deterministic scoring: set arithmetic over URLs, with no model in the loop."""

from __future__ import annotations

import pytest

from src.core.errors import ErrorCode
from src.services.evaluation.scoring import (
    canonical_source,
    citation_precision,
    recall_at_k,
    score_deterministically,
)

ENVS = "https://docs.liara.ir/paas/details/envs/"
DISKS = "https://docs.liara.ir/paas/disks/create/"
FS = "https://docs.liara.ir/paas/details/file-system/"


def _score(**overrides: object):
    values: dict[str, object] = {
        "expected_sources": [ENVS],
        "retrieved_urls": [ENVS],
        "cited_urls": [ENVS],
        "retrieved_evidence_urls": [ENVS],
        "expects_clarification": False,
        "asked_clarification": False,
        "expects_abstention": False,
        "error_code": None,
        "k": 8,
        **overrides,
    }
    return score_deterministically(**values)  # type: ignore[arg-type]


def test_an_anchor_and_a_trailing_slash_are_the_same_page() -> None:
    assert canonical_source(f"{ENVS}#add") == canonical_source(ENVS.rstrip("/"))
    assert canonical_source("HTTPS://DOCS.LIARA.IR/paas/details/envs") == canonical_source(ENVS)


def test_recall_counts_expected_pages_found_within_k() -> None:
    retrieved = [FS, "https://docs.liara.ir/paas/other/", DISKS, ENVS]

    assert recall_at_k([FS, DISKS], retrieved, k=8) == 1.0
    assert recall_at_k([FS, DISKS], retrieved, k=2) == 0.5
    assert recall_at_k([ENVS], retrieved, k=2) == 0.0


def test_recall_refuses_a_case_it_cannot_score() -> None:
    with pytest.raises(ValueError, match="positive k"):
        recall_at_k([ENVS], [ENVS], k=0)
    with pytest.raises(ValueError, match="at least one expected source"):
        recall_at_k([], [ENVS], k=4)


def test_an_uncited_answer_scores_zero_rather_than_being_skipped() -> None:
    assert citation_precision([], [ENVS]) == 0.0
    assert citation_precision([f"{ENVS}#add", DISKS], [ENVS]) == 0.5


def test_a_correct_answer_scores_clean_on_every_deterministic_dimension() -> None:
    scores = _score(retrieved_urls=[ENVS, FS], cited_urls=[f"{ENVS}#add-variable"])

    assert scores.recall_at_k == 1.0
    assert scores.citation_precision == 1.0
    assert scores.citations_grounded is True
    assert scores.clarification_correct is True
    assert scores.abstained is False


def test_a_citation_the_agent_never_retrieved_is_reported_as_ungrounded() -> None:
    scores = _score(cited_urls=[DISKS], retrieved_evidence_urls=[ENVS], expected_sources=[DISKS])

    assert scores.citations_grounded is False


def test_asking_the_expected_clarification_is_correct_and_costs_no_citation_credit() -> None:
    scores = _score(expects_clarification=True, asked_clarification=True, cited_urls=[])

    assert scores.clarification_correct is True
    # A turn that stopped to ask has nothing to cite yet; scoring it as zero
    # precision would penalise exactly the behaviour Q8 and Q9 ask for.
    assert scores.citation_precision == 1.0


def test_answering_outright_when_a_clarification_was_expected_is_wrong() -> None:
    scores = _score(expects_clarification=True, asked_clarification=False)

    assert scores.clarification_correct is False


def test_the_no_evidence_path_is_recorded_as_an_abstention() -> None:
    scores = _score(
        expects_abstention=True,
        error_code=ErrorCode.NO_EVIDENCE,
        cited_urls=[],
    )

    assert scores.abstained is True
    assert scores.abstention_expected is True


def test_a_limit_reached_turn_is_not_mistaken_for_an_abstention() -> None:
    scores = _score(error_code=ErrorCode.AGENT_LIMIT_REACHED)

    assert scores.abstained is False


def test_retrieving_nothing_scores_zero_recall_without_raising() -> None:
    scores = _score(retrieved_urls=[], cited_urls=[])

    assert scores.recall_at_k == 0.0
    assert scores.matched_source_count == 0
