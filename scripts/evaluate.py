"""Run the golden set and write the baseline.

    uv run python -m scripts.evaluate
    uv run python -m scripts.evaluate --no-judge          # deterministic only
    uv run python -m scripts.evaluate --question Q8 --question Q9
    uv run python -m scripts.evaluate --json out/eval.json --dry-run

Needs a reachable database with an active index, and provider credentials — it
answers all ten questions for real. `--no-judge` skips every model call the
harness itself makes, leaving the numbers the plan says to trust.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.core.tracing import configure_tracing, shutdown_tracing
from src.db.session import dispose_engine, get_sessionmaker
from src.services.agent import BoundedAgent
from src.services.agent_tools import build_documentation_tool_registry
from src.services.embeddings import EmbeddingClient
from src.services.evaluation.golden_set import GoldenSetError, load_golden_set
from src.services.evaluation.judge import LlmJudge
from src.services.evaluation.runner import EvaluationReport, evaluate_golden_set, render_baseline
from src.services.gateway import GatewayChatClient

logger = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden-set",
        default=None,
        help="Path to the golden set (default: docs/eval/golden-set.md).",
    )
    parser.add_argument(
        "--question",
        action="append",
        default=[],
        metavar="ID",
        help="Run only these question ids. Repeatable.",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip LLM-as-judge scoring and report the deterministic metrics only.",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Where to write the rendered baseline (default: EVAL_BASELINE_PATH).",
    )
    parser.add_argument("--json", default=None, help="Also write the full report as JSON here.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the golden set, then exit without answering anything.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        questions = load_golden_set(args.golden_set)
    except GoldenSetError as err:
        logger.error("golden set could not be loaded", extra={"cause": str(err)})
        return 2

    if args.question:
        wanted = {qid.strip().upper() for qid in args.question}
        missing = wanted - {q.id.upper() for q in questions}
        if missing:
            logger.error("no such question id", extra={"ids": sorted(missing)})
            return 2
        questions = tuple(q for q in questions if q.id.upper() in wanted)

    logger.info(
        "golden set loaded",
        extra={"question_count": len(questions), "ids": [q.id for q in questions]},
    )
    if args.dry_run:
        return 0

    if not args.no_judge:
        # Fail before spending a single provider call, not after ten of them.
        settings.assert_judge_differs_from_model_under_test()

    configure_tracing(settings)
    sessionmaker = get_sessionmaker()
    judge_client = None
    try:
        async with sessionmaker() as session, GatewayChatClient() as gateway:
            with EmbeddingClient() as embeddings:
                judge = None
                if not args.no_judge:
                    judge, judge_client = LlmJudge.from_settings(settings)
                tools = build_documentation_tool_registry(session, embeddings, settings=settings)
                report = await evaluate_golden_set(
                    session,
                    questions,
                    agent=BoundedAgent(gateway, tools, settings),
                    embeddings=embeddings,
                    judge=judge,
                    settings=settings,
                )
    finally:
        if judge_client is not None:
            await judge_client.close()
        shutdown_tracing()
        await dispose_engine()

    _write(report, args, settings.eval_baseline_path)
    return 0


def _write(report: EvaluationReport, args: argparse.Namespace, default_baseline: str) -> None:
    baseline_path = Path(args.baseline or default_baseline)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(render_baseline(report), encoding="utf-8")
    logger.info("baseline written", extra={"path": str(baseline_path)})

    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(_jsonable(report), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("json report written", extra={"path": str(json_path)})

    print(render_baseline(report))


def _jsonable(report: EvaluationReport) -> dict[str, object]:
    return {
        "generated_at": report.generated_at.isoformat(),
        "model_under_test": report.model_under_test,
        "judge_model": report.judge_model,
        "k": report.k,
        "similarity_threshold": report.similarity_threshold,
        "index_version": report.index_version,
        "aggregates": {
            "recall_at_k": report.mean_recall_at_k,
            "citation_correctness": report.mean_citation_precision,
            "grounded_citation_rate": report.grounded_citation_rate,
            "clarification_accuracy": report.clarification_accuracy,
            "abstention_accuracy": report.abstention_accuracy,
            "unsupported_claim_rate": report.unsupported_claim_rate,
            "mean_latency_ms": report.mean_latency_ms,
            "total_tokens": report.total_tokens,
            "answer_relevance": report.mean_judge_score("answer_relevance"),
            "answer_completeness": report.mean_judge_score("answer_completeness"),
            "groundedness": report.mean_judge_score("groundedness"),
        },
        "questions": [
            {
                "id": outcome.question.id,
                "question": outcome.question.question,
                "difficulty": outcome.question.difficulty,
                "answer": outcome.answer,
                "cited_urls": list(outcome.cited_urls),
                "retrieved_urls": list(outcome.retrieved_urls),
                "error_code": outcome.error_code.value if outcome.error_code else None,
                "latency_ms": outcome.latency_ms,
                "total_tokens": outcome.total_tokens,
                "tool_calls": outcome.tool_calls,
                "rewrites": outcome.rewrites,
                "scores": asdict(outcome.scores),
                # Kept verbatim: 16.4 asks for ten judge verdicts to be read
                # against human judgement, which needs the rationale, not a
                # number.
                "verdict": asdict(outcome.verdict) if outcome.verdict else None,
            }
            for outcome in report.outcomes
        ],
    }


def main() -> int:
    configure_logging()
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
