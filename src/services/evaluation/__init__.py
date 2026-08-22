"""Golden-set evaluation: parsing, deterministic scoring, and the LLM judge.

Two layers, deliberately separated. `scoring` computes Recall@k and citation
correctness with no model in the loop, which is why those numbers carry the
most weight (plan §26). `judge` adds the qualitative dimensions and is the
layer that can be wrong.
"""

from src.services.evaluation.golden_set import (
    GoldenQuestion,
    GoldenSetError,
    load_golden_set,
    parse_golden_set,
)
from src.services.evaluation.judge import JudgeVerdict, LlmJudge
from src.services.evaluation.runner import (
    EvaluationReport,
    QuestionOutcome,
    evaluate_golden_set,
    render_baseline,
)
from src.services.evaluation.scoring import (
    DeterministicScores,
    canonical_source,
    score_deterministically,
)

__all__ = [
    "DeterministicScores",
    "EvaluationReport",
    "GoldenQuestion",
    "GoldenSetError",
    "JudgeVerdict",
    "LlmJudge",
    "QuestionOutcome",
    "canonical_source",
    "evaluate_golden_set",
    "load_golden_set",
    "parse_golden_set",
    "render_baseline",
    "score_deterministically",
]
