"""The golden set must load exactly as written, or refuse to load at all."""

from __future__ import annotations

import pytest

from src.services.evaluation.golden_set import (
    DEFAULT_GOLDEN_SET_PATH,
    GoldenSetError,
    load_golden_set,
    parse_golden_set,
)

_MINIMAL = """## Q1

**question:** چطور دامنه وصل کنم؟

**expected_answer_points:**

- افزودن دامنه از منوی دامنه‌ها

**expected_sources:**

- [https://docs.liara.ir/paas/domains/add-domain/](https://docs.liara.ir/paas/domains/add-domain/)

**expected_clarification:** none

**expected_abstention:** false

**difficulty:** easy

**tags:** service=paas, runtime=any, framework=any
"""


def test_all_ten_questions_load_with_their_expected_sources() -> None:
    questions = load_golden_set()

    assert [q.id for q in questions] == [f"Q{n}" for n in range(1, 11)]
    assert all(q.question for q in questions)
    assert all(q.expected_sources for q in questions), "every question must name its pages"
    assert all(q.expected_answer_points for q in questions)
    assert all(
        source.startswith("https://docs.liara.ir/")
        for q in questions
        for source in q.expected_sources
    )


def test_the_set_carries_the_behaviours_the_plan_asks_it_to_cover() -> None:
    questions = {q.id: q for q in load_golden_set(DEFAULT_GOLDEN_SET_PATH)}

    # Plan §26: two clarification questions and exactly one abstention.
    assert [q.id for q in questions.values() if q.expects_clarification] == ["Q8", "Q9"]
    assert [q.id for q in questions.values() if q.expected_abstention] == ["Q10"]
    assert questions["Q9"].tags["service"] == "dbaas"
    assert len(questions["Q5"].expected_sources) == 3


def test_a_bare_url_is_accepted_as_well_as_a_markdown_link() -> None:
    text = _MINIMAL.replace(
        "- [https://docs.liara.ir/paas/domains/add-domain/]"
        "(https://docs.liara.ir/paas/domains/add-domain/)",
        "- https://docs.liara.ir/paas/domains/add-domain/",
    )

    (question,) = parse_golden_set(text)

    assert question.expected_sources == ("https://docs.liara.ir/paas/domains/add-domain/",)


def test_a_question_missing_its_sources_is_refused_not_silently_scored_zero() -> None:
    text = _MINIMAL.replace(
        "**expected_sources:**\n\n"
        "- [https://docs.liara.ir/paas/domains/add-domain/]"
        "(https://docs.liara.ir/paas/domains/add-domain/)\n",
        "**expected_sources:**\n",
    )

    with pytest.raises(GoldenSetError, match="expected_sources"):
        parse_golden_set(text, source="fixture.md")


def test_a_non_boolean_abstention_is_refused() -> None:
    text = _MINIMAL.replace("**expected_abstention:** false", "**expected_abstention:** maybe")

    with pytest.raises(GoldenSetError, match="expected_abstention"):
        parse_golden_set(text, source="fixture.md")


def test_a_file_without_question_headings_is_refused() -> None:
    with pytest.raises(GoldenSetError, match="no `## Q<n>`"):
        parse_golden_set("# Golden Evaluation Set\n\nهیچ سؤالی.\n", source="fixture.md")


def test_a_missing_file_names_the_path_it_looked_at() -> None:
    with pytest.raises(GoldenSetError, match="does-not-exist.md"):
        load_golden_set("docs/eval/does-not-exist.md")
