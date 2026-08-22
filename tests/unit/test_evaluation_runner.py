"""The harness must read clarification, abstention, and citations off a real turn.

Retrieval and the agent are substituted here; what is under test is whether the
harness draws the right conclusion from what they return. Whether the live
system actually behaves this way is task 16.4's run, not this test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.core.config import Settings
from src.core.errors import ErrorCode
from src.services.agent import AgentCitation, AgentTurnResult
from src.services.evaluation import runner as runner_module
from src.services.evaluation.golden_set import parse_golden_set
from src.services.evaluation.runner import evaluate_golden_set, render_baseline

ENVS = "https://docs.liara.ir/paas/details/envs/"
FS = "https://docs.liara.ir/paas/details/file-system/"
PRIVATE = "https://docs.liara.ir/paas/details/private-network/"

GOLDEN = f"""## Q1

**question:** چطور متغیر محیطی تنظیم کنم؟

**expected_answer_points:**

- از بخش تنظیمات

**expected_sources:**

- {ENVS}

**expected_clarification:** none

**expected_abstention:** false

**difficulty:** easy

**tags:** service=paas, runtime=any, framework=any

## Q2

**question:** برنامه‌ام باید فایل بنویسه؛ کجا ذخیره‌ش کنم؟

**expected_answer_points:**

- موقتی یا ماندگار بودن را بپرس

**expected_sources:**

- {FS}

**expected_clarification:** فایل‌ها موقتی‌اند یا ماندگار؟

**expected_abstention:** false

**difficulty:** medium

**tags:** service=paas, runtime=any, framework=any

## Q3

**question:** latency تضمین‌شده p99 چقدر است؟

**expected_answer_points:**

- عدد تضمین‌شده‌ای اعلام نشده است

**expected_sources:**

- {PRIVATE}

**expected_clarification:** none

**expected_abstention:** true

**difficulty:** hard

**tags:** service=paas, runtime=any, framework=any
"""


@dataclass
class _Retrieved:
    citation_url: str
    index_version_id: str = "index-1"


class StubEmbeddings:
    def embed_one(self, text: str) -> list[float]:
        return [0.0]


class StubAgent:
    """Returns one canned turn per question, in order."""

    def __init__(self, results: list[AgentTurnResult]) -> None:
        self.results = results
        self.questions: list[str] = []

    async def run(self, executor: Any, *, question: str, **kwargs: Any) -> AgentTurnResult:
        self.questions.append(question)
        return self.results.pop(0)


def _turn(
    content: str,
    *,
    urls: tuple[str, ...] = (),
    needs_clarification: bool = False,
    error_code: ErrorCode | None = None,
) -> AgentTurnResult:
    citations = tuple(
        AgentCitation(
            evidence_id=f"chunk:{index}",
            url=url,
            page_title=None,
            section_title=None,
            source_commit="abc123",
        )
        for index, url in enumerate(urls)
    )
    return AgentTurnResult(
        content=content,
        messages=(),
        tool_calls=1,
        rewrites=0,
        total_tokens=100,
        citations=citations,
        needs_clarification=needs_clarification,
        error_code=error_code,
    )


@pytest.fixture
def stub_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(executor: Any, query: str, embeddings: Any, **kwargs: Any):
        return [_Retrieved(ENVS), _Retrieved(FS), _Retrieved(PRIVATE)]

    monkeypatch.setattr(runner_module, "search_documentation", fake_search)


def _settings() -> Settings:
    return Settings(_env_file=None, eval_recall_k=8, llm_model="gemini-3.7-flash")


@pytest.mark.asyncio
async def test_the_harness_reads_each_expected_behaviour_off_the_turn(
    stub_retrieval: None,
) -> None:
    questions = parse_golden_set(GOLDEN)
    agent = StubAgent(
        [
            _turn("از بخش تنظیمات…", urls=(f"{ENVS}#add",)),
            _turn("فایل‌ها موقتی‌اند یا ماندگار؟", needs_clarification=True),
            _turn("عدد تضمین‌شده‌ای اعلام نشده است.", error_code=ErrorCode.NO_EVIDENCE),
        ]
    )

    report = await evaluate_golden_set(
        object(),
        questions,
        agent=agent,  # type: ignore[arg-type]
        embeddings=StubEmbeddings(),
        judge=None,
        settings=_settings(),
    )

    answered, clarified, abstained = report.outcomes
    assert answered.scores.recall_at_k == 1.0
    assert answered.scores.citation_precision == 1.0
    assert clarified.scores.clarification_asked is True
    assert clarified.clarification_ok is True
    assert abstained.scores.abstained is True
    assert abstained.abstention_ok is True
    assert report.clarification_accuracy == 1.0
    assert report.abstention_accuracy == 1.0
    assert report.index_version == "index-1"
    assert report.judge_model is None


@pytest.mark.asyncio
async def test_answering_instead_of_asking_and_inventing_instead_of_abstaining_both_fail(
    stub_retrieval: None,
) -> None:
    questions = parse_golden_set(GOLDEN)
    agent = StubAgent(
        [
            _turn("از بخش تنظیمات…", urls=(ENVS,)),
            # Answers outright where the golden set expects a question first.
            _turn("در /tmp ذخیره کن.", urls=(FS,)),
            # States a number the documentation does not contain.
            _turn("latency تضمین‌شده p99 برابر ۲ میلی‌ثانیه است.", urls=(PRIVATE,)),
        ]
    )

    report = await evaluate_golden_set(
        object(),
        questions,
        agent=agent,  # type: ignore[arg-type]
        embeddings=StubEmbeddings(),
        judge=None,
        settings=_settings(),
    )

    _, clarified, invented = report.outcomes
    assert clarified.clarification_ok is False
    # Without a judge there is nothing to confirm a soft refusal, so an answer
    # that did not take the NO_EVIDENCE path counts against abstention.
    assert invented.abstention_ok is False
    assert report.clarification_accuracy == pytest.approx(2 / 3)
    assert report.abstention_accuracy == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_a_question_that_retrieves_nothing_scores_zero_and_the_run_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.core.errors import RescueError

    async def empty_search(executor: Any, query: str, embeddings: Any, **kwargs: Any):
        raise RescueError(ErrorCode.NO_RESULTS_ABOVE_THRESHOLD, detail="nothing above threshold")

    monkeypatch.setattr(runner_module, "search_documentation", empty_search)
    questions = parse_golden_set(GOLDEN)[:1]
    agent = StubAgent([_turn("پاسخی نیست", error_code=ErrorCode.NO_EVIDENCE)])

    report = await evaluate_golden_set(
        object(),
        questions,
        agent=agent,  # type: ignore[arg-type]
        embeddings=StubEmbeddings(),
        judge=None,
        settings=_settings(),
    )

    assert report.mean_recall_at_k == 0.0
    assert report.outcomes[0].retrieved_urls == ()


@pytest.mark.asyncio
async def test_the_rendered_baseline_names_the_models_and_every_question(
    stub_retrieval: None,
) -> None:
    questions = parse_golden_set(GOLDEN)
    agent = StubAgent(
        [
            _turn("پاسخ", urls=(ENVS,)),
            _turn("سؤال تکمیلی", needs_clarification=True),
            _turn("خودداری", error_code=ErrorCode.NO_EVIDENCE),
        ]
    )
    report = await evaluate_golden_set(
        object(),
        questions,
        agent=agent,  # type: ignore[arg-type]
        embeddings=StubEmbeddings(),
        judge=None,
        settings=_settings(),
    )

    rendered = render_baseline(report)

    assert "model_under_test: `gemini-3.7-flash`" in rendered
    assert "(judge disabled)" in rendered
    assert all(f"| {qid} |" in rendered for qid in ("Q1", "Q2", "Q3"))
    assert "Recall@8" in rendered


@pytest.mark.asyncio
async def test_a_question_the_agent_cannot_answer_is_recorded_not_fatal(
    stub_retrieval: None,
) -> None:
    from src.core.errors import RescueError

    class FailingAgent:
        async def run(self, executor: Any, *, question: str, **kwargs: Any) -> AgentTurnResult:
            raise RescueError(
                ErrorCode.NO_RESULTS_ABOVE_THRESHOLD,
                detail="a tool found no matching section",
            )

    report = await evaluate_golden_set(
        object(),
        parse_golden_set(GOLDEN)[:1],
        agent=FailingAgent(),  # type: ignore[arg-type]
        embeddings=StubEmbeddings(),
        judge=None,
        settings=_settings(),
    )

    (outcome,) = report.outcomes
    assert outcome.error_code is ErrorCode.NO_RESULTS_ABOVE_THRESHOLD
    assert outcome.answer == ""
    # Retrieval still ran and still scores: the failure was in answering.
    assert outcome.scores.recall_at_k == 1.0
