"""Runs the golden set end to end and renders the baseline.

One pass per question, in two parts:

1. A direct retrieval call, scored with Recall@k. Measuring retrieval through
   the agent would confound a retrieval regression with a change in how the
   agent phrases its queries.
2. A full agent turn, scored for citations, clarification, abstention, and —
   only then — by the judge.

Deterministic scores are computed for every question even when the judge is
switched off, because those are the numbers the plan says to trust.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from typing import Any, Protocol

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.tracing import opik_turn
from src.services.agent import AgentTurnResult, BoundedAgent
from src.services.evaluation.golden_set import GoldenQuestion
from src.services.evaluation.judge import JudgeVerdict, LlmJudge
from src.services.evaluation.scoring import DeterministicScores, score_deterministically
from src.services.gateway import GatewayTelemetry
from src.services.retrieval import RetrievalTelemetry, search_documentation

logger = get_logger(__name__)

#: Retrieval failures that are answers about the corpus, not harness faults.
_EMPTY_RETRIEVAL_CODES = frozenset(
    {ErrorCode.NO_RESULTS_ABOVE_THRESHOLD, ErrorCode.NO_RESULTS_FOR_FILTER}
)


class EmbeddingProvider(Protocol):
    def embed_one(self, text: str) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class QuestionOutcome:
    question: GoldenQuestion
    answer: str
    cited_urls: tuple[str, ...]
    retrieved_urls: tuple[str, ...]
    scores: DeterministicScores
    verdict: JudgeVerdict | None
    latency_ms: int
    total_tokens: int
    tool_calls: int
    rewrites: int
    error_code: ErrorCode | None

    @property
    def clarification_ok(self) -> bool:
        return self.scores.clarification_correct

    @property
    def abstention_ok(self) -> bool:
        """Hard refusal, or a judge-confirmed refusal to invent the missing fact.

        Q10 may legitimately answer — citing the qualitative claim the page does
        make — as long as it does not manufacture the number it was asked for.
        Requiring the NO_EVIDENCE path would fail a correct answer.
        """
        if not self.scores.abstention_expected:
            return not self.scores.abstained
        if self.scores.abstained:
            return True
        return self.verdict is not None and self.verdict.abstention_respected


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    generated_at: datetime
    model_under_test: str
    judge_model: str | None
    k: int
    similarity_threshold: float
    index_version: str | None
    outcomes: tuple[QuestionOutcome, ...]

    @property
    def mean_recall_at_k(self) -> float:
        return mean(o.scores.recall_at_k for o in self.outcomes)

    @property
    def mean_citation_precision(self) -> float:
        return mean(o.scores.citation_precision for o in self.outcomes)

    @property
    def clarification_accuracy(self) -> float:
        return _share(o.clarification_ok for o in self.outcomes)

    @property
    def abstention_accuracy(self) -> float:
        return _share(o.abstention_ok for o in self.outcomes)

    @property
    def grounded_citation_rate(self) -> float:
        return _share(o.scores.citations_grounded for o in self.outcomes)

    @property
    def unsupported_claim_rate(self) -> float:
        judged = [o for o in self.outcomes if o.verdict is not None]
        if not judged:
            return 0.0
        return _share(o.verdict.has_unsupported_claims for o in judged)  # type: ignore[union-attr]

    @property
    def mean_latency_ms(self) -> float:
        return mean(o.latency_ms for o in self.outcomes)

    @property
    def total_tokens(self) -> int:
        judged = sum(o.verdict.total_tokens for o in self.outcomes if o.verdict is not None)
        return sum(o.total_tokens for o in self.outcomes) + judged

    def mean_judge_score(self, dimension: str) -> float | None:
        values = [getattr(o.verdict, dimension) for o in self.outcomes if o.verdict is not None]
        return mean(values) if values else None


def _share(values: Iterable[bool]) -> float:
    items = list(values)
    return sum(1 for value in items if value) / len(items) if items else 0.0


async def evaluate_golden_set(
    executor: Any,
    questions: Sequence[GoldenQuestion],
    *,
    agent: BoundedAgent,
    embeddings: EmbeddingProvider,
    judge: LlmJudge | None = None,
    settings: Settings | None = None,
) -> EvaluationReport:
    settings = settings or get_settings()
    if not questions:
        raise ValueError("the golden set is empty; nothing to evaluate")

    outcomes: list[QuestionOutcome] = []
    index_version: str | None = None
    for question in questions:
        outcome, seen_version = await _evaluate_one(
            executor,
            question,
            agent=agent,
            embeddings=embeddings,
            judge=judge,
            settings=settings,
        )
        index_version = index_version or seen_version
        outcomes.append(outcome)

    return EvaluationReport(
        generated_at=datetime.now(UTC),
        model_under_test=settings.llm_model,
        judge_model=settings.eval_judge_model if judge is not None else None,
        k=settings.eval_recall_k,
        similarity_threshold=settings.retrieval_similarity_threshold,
        index_version=index_version,
        outcomes=tuple(outcomes),
    )


async def _evaluate_one(
    executor: Any,
    question: GoldenQuestion,
    *,
    agent: BoundedAgent,
    embeddings: EmbeddingProvider,
    judge: LlmJudge | None,
    settings: Settings,
) -> tuple[QuestionOutcome, str | None]:
    with opik_turn("eval.question", tags={"question_id": question.id}) as turn:
        turn.metadata(
            difficulty=question.difficulty,
            expects_clarification=question.expects_clarification,
            expects_abstention=question.expected_abstention,
        )
        turn.content(question=question.question)

        retrieved_urls, index_version = await _retrieval_pass(
            executor, question, embeddings, settings=settings
        )
        started = time.perf_counter()
        failure: ErrorCode | None = None
        try:
            result = await agent.run(
                executor,
                question=question.question,
                telemetry=GatewayTelemetry(question=question.question),
            )
        except RescueError as err:
            # One question the system cannot answer is a result, not a crashed
            # run: the report must still cover all ten, with this one's cause
            # named rather than averaged away.
            logger.warning(
                "golden-set question failed",
                extra={"question_id": question.id, "error_code": err.code.value},
            )
            turn.error(err.code.value, err.detail)
            failure = err.code
            result = _failed_turn(err)
        latency_ms = int((time.perf_counter() - started) * 1000)

        cited_urls = tuple(citation.url for citation in result.citations)
        scores = score_deterministically(
            expected_sources=question.expected_sources,
            retrieved_urls=retrieved_urls,
            cited_urls=cited_urls,
            retrieved_evidence_urls=_evidence_urls(result),
            expects_clarification=question.expects_clarification,
            asked_clarification=result.needs_clarification,
            expects_abstention=question.expected_abstention,
            error_code=failure or result.error_code,
            k=settings.eval_recall_k,
        )
        verdict = None
        if judge is not None and failure is None:
            verdict = await judge.evaluate(
                executor,
                question=question.question,
                expected_answer_points=question.expected_answer_points,
                expected_sources=question.expected_sources,
                expected_clarification=question.expected_clarification,
                expected_abstention=question.expected_abstention,
                answer=result.content,
                cited_urls=cited_urls,
            )

        turn.metadata(
            recall_at_k=round(scores.recall_at_k, 4),
            citation_precision=round(scores.citation_precision, 4),
            clarification_correct=scores.clarification_correct,
            abstained=scores.abstained,
            latency_ms=latency_ms,
        )
        return (
            QuestionOutcome(
                question=question,
                answer=result.content,
                cited_urls=cited_urls,
                retrieved_urls=retrieved_urls,
                scores=scores,
                verdict=verdict,
                latency_ms=latency_ms,
                total_tokens=result.total_tokens,
                tool_calls=result.tool_calls,
                rewrites=result.rewrites,
                error_code=failure or result.error_code,
            ),
            index_version,
        )


def _failed_turn(err: RescueError) -> AgentTurnResult:
    """Stand-in for a turn that never produced an answer."""
    return AgentTurnResult(
        content="",
        messages=(),
        tool_calls=0,
        rewrites=0,
        total_tokens=0,
        error_code=err.code,
    )


async def _retrieval_pass(
    executor: Any,
    question: GoldenQuestion,
    embeddings: EmbeddingProvider,
    *,
    settings: Settings,
) -> tuple[tuple[str, ...], str | None]:
    try:
        results = await search_documentation(
            executor,
            question.question,
            embeddings,
            settings=settings,
            top_k=settings.eval_recall_k,
            telemetry=RetrievalTelemetry(),
        )
    except RescueError as err:
        if err.code in _EMPTY_RETRIEVAL_CODES:
            # A real, reportable zero — not a harness failure. Recall@k for
            # this question is 0 and the run continues.
            logger.info(
                "golden-set question retrieved nothing above threshold",
                extra={"question_id": question.id, "error_code": err.code.value},
            )
            return (), None
        raise
    version = str(results[0].index_version_id) if results else None
    return tuple(result.citation_url for result in results), version


def _evidence_urls(result: AgentTurnResult) -> tuple[str, ...]:
    """Every documentation URL the agent actually saw during the turn.

    Read back out of the tool messages the agent appended, which carry the
    `liara_documentation_evidence` envelope built in `src/services/agent.py`.
    Read defensively: a shape change here should cost a grounding check, not
    the whole run.
    """
    urls: list[str] = []
    for message in result.messages:
        if message.get("role") != "tool":
            continue
        try:
            envelope = json.loads(message.get("content") or "")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(envelope, dict):
            continue
        payload = envelope.get("content")
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, Mapping):
                continue
            citation = item.get("citation")
            if isinstance(citation, Mapping) and isinstance(citation.get("url"), str):
                urls.append(citation["url"])
    return tuple(urls)


def render_baseline(report: EvaluationReport) -> str:
    """The committed baseline: aggregates first, then every question's row."""
    lines = [
        "# Golden Set Baseline",
        "",
        "خروجی `scripts/evaluate.py`. اعداد بخش «قطعی» بدون هیچ فراخوانی مدل محاسبه",
        "شده‌اند؛ اعداد داور با مدل داور محاسبه شده‌اند و قبل از اعتماد باید دستی",
        "بازبینی شوند (طرح §۲۶).",
        "",
        f"- generated_at: `{report.generated_at.isoformat(timespec='seconds')}`",
        f"- model_under_test: `{report.model_under_test}`",
        f"- judge_model: `{report.judge_model or '(judge disabled)'}`",
        f"- k: `{report.k}`",
        f"- similarity_threshold: `{report.similarity_threshold}`",
        f"- index_version: `{report.index_version or '(none)'}`",
        "",
        "## Deterministic",
        "",
        "| متریک | مقدار |",
        "|---|---:|",
        f"| Recall@{report.k} | {report.mean_recall_at_k:.3f} |",
        f"| Citation correctness | {report.mean_citation_precision:.3f} |",
        f"| Grounded citations | {report.grounded_citation_rate:.3f} |",
        f"| Clarification correctness | {report.clarification_accuracy:.3f} |",
        f"| Abstention correctness | {report.abstention_accuracy:.3f} |",
        f"| Mean latency (ms) | {report.mean_latency_ms:.0f} |",
        f"| Total tokens | {report.total_tokens} |",
        "",
    ]
    if report.judge_model:
        lines += [
            "## Judge",
            "",
            "| متریک | مقدار |",
            "|---|---:|",
            f"| Answer relevance | {_fmt(report.mean_judge_score('answer_relevance'))} |",
            f"| Answer completeness | {_fmt(report.mean_judge_score('answer_completeness'))} |",
            f"| Groundedness | {_fmt(report.mean_judge_score('groundedness'))} |",
            f"| Unsupported-claim rate | {report.unsupported_claim_rate:.3f} |",
            "",
        ]
    lines += [
        "## Per question",
        "",
        f"| # | difficulty | Recall@{report.k} | citation | clarification | abstention | "
        "tokens | ms |",
        "|---|---|---:|---:|:-:|:-:|---:|---:|",
    ]
    for outcome in report.outcomes:
        lines.append(
            f"| {outcome.question.id} | {outcome.question.difficulty} "
            f"| {outcome.scores.recall_at_k:.2f} | {outcome.scores.citation_precision:.2f} "
            f"| {'✓' if outcome.clarification_ok else '✗'} "
            f"| {'✓' if outcome.abstention_ok else '✗'} "
            f"| {outcome.total_tokens} | {outcome.latency_ms} |"
        )
    lines.append("")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"
