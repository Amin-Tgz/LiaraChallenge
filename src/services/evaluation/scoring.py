"""Deterministic golden-set metrics. No model is called from this module.

Plan §26 puts the most weight on these numbers precisely because nothing here
can have an opinion: Recall@k and citation correctness are set arithmetic over
URLs, and clarification and abstention are read off the agent's own result.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from src.core.errors import ErrorCode


def canonical_source(url: str) -> str:
    """Reduce a documentation URL to the page it identifies.

    Citations deep-link to a heading anchor while the golden set names the
    page, and the docs site serves the same page with and without a trailing
    slash. Comparing raw strings would score a correct citation as a miss.
    """
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def _canonical_set(urls: Iterable[str]) -> set[str]:
    return {canonical_source(url) for url in urls if url and url.strip()}


@dataclass(frozen=True, slots=True)
class DeterministicScores:
    """Everything about one answer that can be checked without a judge."""

    recall_at_k: float
    k: int
    expected_source_count: int
    matched_source_count: int
    #: Share of the answer's citations that point at an expected page.
    citation_precision: float
    citation_count: int
    #: Every citation resolved to a chunk retrieved this turn. The agent
    #: enforces this; the harness verifies it rather than trusting it.
    citations_grounded: bool
    clarification_expected: bool
    clarification_asked: bool
    clarification_correct: bool
    abstention_expected: bool
    #: The agent's own NO_EVIDENCE path. A soft, in-answer refusal is not this,
    #: and is left for the judge to assess.
    abstained: bool


def recall_at_k(expected_sources: Iterable[str], retrieved_urls: Sequence[str], k: int) -> float:
    """Share of the expected pages that appear in the top `k` retrieved results."""
    if k <= 0:
        raise ValueError("recall@k needs a positive k")
    expected = _canonical_set(expected_sources)
    if not expected:
        raise ValueError("recall@k needs at least one expected source")
    retrieved = _canonical_set(retrieved_urls[:k])
    return len(expected & retrieved) / len(expected)


def citation_precision(cited_urls: Sequence[str], expected_sources: Iterable[str]) -> float:
    """Share of citations that point at a page the golden set expects.

    An answer with no citations scores zero rather than being skipped: for a
    documentation product an uncited technical claim is the failure, not an
    absence of data.
    """
    cited = _canonical_set(cited_urls)
    if not cited:
        return 0.0
    return len(cited & _canonical_set(expected_sources)) / len(cited)


def score_deterministically(
    *,
    expected_sources: Iterable[str],
    retrieved_urls: Sequence[str],
    cited_urls: Sequence[str],
    retrieved_evidence_urls: Sequence[str],
    expects_clarification: bool,
    asked_clarification: bool,
    expects_abstention: bool,
    error_code: ErrorCode | None,
    k: int,
) -> DeterministicScores:
    expected = _canonical_set(expected_sources)
    cited = _canonical_set(cited_urls)
    abstained = error_code is ErrorCode.NO_EVIDENCE

    if asked_clarification or abstained:
        # A turn that stopped to ask, or refused for want of evidence, produced
        # no citations by design. Scoring it against expected pages would
        # punish the behavior the golden set is asking for.
        precision = 1.0 if not cited else citation_precision(cited_urls, expected_sources)
    else:
        precision = citation_precision(cited_urls, expected_sources)

    return DeterministicScores(
        recall_at_k=recall_at_k(expected, retrieved_urls, k) if retrieved_urls else 0.0,
        k=k,
        expected_source_count=len(expected),
        matched_source_count=len(expected & _canonical_set(retrieved_urls[:k])),
        citation_precision=precision,
        citation_count=len(cited),
        citations_grounded=cited <= _canonical_set(retrieved_evidence_urls),
        clarification_expected=expects_clarification,
        clarification_asked=asked_clarification,
        clarification_correct=expects_clarification == asked_clarification,
        abstention_expected=expects_abstention,
        abstained=abstained,
    )
