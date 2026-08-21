"""A hard filter must never manufacture a documentation gap.

Found by driving the Skill through a real coding agent: `runtime="node"` — the
value the tool's own description offered as an example — matched zero chunks,
because the corpus stores `nodejs`. The agent got `NO_RESULTS_ABOVE_THRESHOLD`,
correctly reported "the documentation has no answer", and was wrong: the
documentation had the answer, and the filter had thrown it away.

That is the exact collapse RULES.md §1 exists to prevent, reached by a route the
error taxonomy did not anticipate. Two defenses, tested here and in
`tests/integration/test_retrieval_errors.py`: normalize the aliases people
actually type, and give an unmatched filter its own code so the remaining cases
cannot be read as a gap.
"""

from __future__ import annotations

import pytest

from src.core.errors import ERROR_SPECS, ErrorCode
from src.services.retrieval import RetrievalIntent


@pytest.mark.parametrize(
    ("typed", "canonical"),
    [
        ("node", "nodejs"),
        ("Node.js", "nodejs"),
        ("NodeJS", "nodejs"),
        ("javascript", "nodejs"),
        ("ts", "nodejs"),
        ("py", "python"),
        ("python3", "python"),
        ("golang", "go"),
        (".net", "dotnet"),
        ("C#", "dotnet"),
    ],
)
def test_runtime_aliases_resolve_to_the_token_the_corpus_stores(typed: str, canonical: str) -> None:
    intent = RetrievalIntent(explicit_filters={"runtime": typed})
    assert intent.explicit_filters["runtime"] == canonical


@pytest.mark.parametrize("value", ["nodejs", "python", "php", "go", "docker", "dotnet", "static"])
def test_the_corpus_vocabulary_survives_normalization_unchanged(value: str) -> None:
    # Every value the index actually uses must pass through untouched, or the
    # alias map would break the callers who already got it right.
    intent = RetrievalIntent(explicit_filters={"runtime": value})
    assert intent.explicit_filters["runtime"] == value


def test_an_unknown_runtime_is_left_alone_rather_than_guessed() -> None:
    # Silently rewriting an unrecognized value to the nearest known one would
    # answer a question the user did not ask. It is passed through, and the
    # unmatched-filter check then names it.
    intent = RetrievalIntent(explicit_filters={"runtime": "haskell"})
    assert intent.explicit_filters["runtime"] == "haskell"


def test_service_and_framework_are_not_aliased() -> None:
    # Only `runtime` has a documented alias problem. Inventing mappings for the
    # other two would be guessing at vocabulary nobody has observed.
    intent = RetrievalIntent(explicit_filters={"service": "node", "framework": "node"})
    assert intent.explicit_filters["service"] == "node"
    assert intent.explicit_filters["framework"] == "node"


def test_an_unmatched_filter_and_a_documentation_gap_are_different_errors() -> None:
    gap = ERROR_SPECS[ErrorCode.NO_RESULTS_ABOVE_THRESHOLD]
    bad_filter = ERROR_SPECS[ErrorCode.NO_RESULTS_FOR_FILTER]
    assert gap.code is not bad_filter.code
    assert gap.message_fa != bad_filter.message_fa
    # The filter message must not let a reader conclude the docs lack an answer.
    assert "نبود پاسخ در مستندات نیست" in bad_filter.message_fa
