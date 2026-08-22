"""Reader for `docs/eval/golden-set.md`.

The golden set is written by hand in Markdown so it stays reviewable in a pull
request rather than becoming an opaque fixture. This module is the only place
that knows its shape, and it refuses to load a set it does not fully
understand: a question that silently loses its `expected_sources` would report
Recall@k of zero and look like a retrieval regression.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Repository-relative default, so the harness and the plan cannot drift apart.
DEFAULT_GOLDEN_SET_PATH: Final = Path("docs/eval/golden-set.md")

_QUESTION_HEADING = re.compile(r"^##\s+(Q\d+)\s*$", re.MULTILINE)
_FIELD = re.compile(r"^\*\*([a-z_]+):\*\*[ \t]*(.*)$", re.MULTILINE)
_BULLET = re.compile(r"^-\s+(.*\S)\s*$", re.MULTILINE)
_MARKDOWN_LINK = re.compile(r"^\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)$")

_REQUIRED_FIELDS: Final = (
    "question",
    "expected_answer_points",
    "expected_sources",
    "expected_clarification",
    "expected_abstention",
    "difficulty",
    "tags",
)
_NONE_MARKERS: Final = frozenset({"none", "-", "—"})


class GoldenSetError(ValueError):
    """The golden set could not be read as written.

    Not in the `ErrorCode` taxonomy on purpose: that taxonomy covers causes a
    user or an operator meets through the API, the logs, or the dashboard. This
    one can only be reached by a developer editing a checked-in Markdown file,
    and it is fixed by editing the file, not by operating the system.
    """


@dataclass(frozen=True, slots=True)
class GoldenQuestion:
    """One hand-written question and everything a correct answer must satisfy."""

    id: str
    question: str
    expected_answer_points: tuple[str, ...]
    expected_sources: tuple[str, ...]
    #: The clarification the assistant is expected to ask first, or None when
    #: it should answer outright.
    expected_clarification: str | None
    #: Whether the assistant must decline to state something the documentation
    #: does not contain. The single most valuable row in the set.
    expected_abstention: bool
    difficulty: str
    tags: dict[str, str]
    notes: str | None = None

    @property
    def expects_clarification(self) -> bool:
        return self.expected_clarification is not None


def load_golden_set(path: Path | str | None = None) -> tuple[GoldenQuestion, ...]:
    target = Path(path) if path is not None else DEFAULT_GOLDEN_SET_PATH
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as err:
        raise GoldenSetError(f"golden set unreadable at {target}: {err}") from err
    return parse_golden_set(text, source=str(target))


def parse_golden_set(text: str, *, source: str = "<string>") -> tuple[GoldenQuestion, ...]:
    blocks = _split_questions(text)
    if not blocks:
        raise GoldenSetError(f"{source} contains no `## Q<n>` question headings")

    questions = [_parse_question(qid, body, source=source) for qid, body in blocks]
    duplicates = {q.id for q in questions if [x.id for x in questions].count(q.id) > 1}
    if duplicates:
        raise GoldenSetError(f"{source} repeats question id(s): {', '.join(sorted(duplicates))}")
    return tuple(questions)


def _split_questions(text: str) -> list[tuple[str, str]]:
    matches = list(_QUESTION_HEADING.finditer(text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1), text[match.end() : end]))
    return blocks


def _parse_question(qid: str, body: str, *, source: str) -> GoldenQuestion:
    fields = _parse_fields(body)
    missing = [name for name in _REQUIRED_FIELDS if name not in fields]
    if missing:
        raise GoldenSetError(f"{source} {qid} is missing: {', '.join(missing)}")

    sources = tuple(
        _link_target(item, qid=qid, source=source) for item in fields["expected_sources"][1]
    )
    if not sources:
        raise GoldenSetError(f"{source} {qid} lists no expected_sources")
    points = tuple(fields["expected_answer_points"][1])
    if not points:
        raise GoldenSetError(f"{source} {qid} lists no expected_answer_points")

    return GoldenQuestion(
        id=qid,
        question=_require_inline(fields, "question", qid=qid, source=source),
        expected_answer_points=points,
        expected_sources=sources,
        expected_clarification=_optional_inline(fields["expected_clarification"][0]),
        expected_abstention=_parse_bool(fields["expected_abstention"][0], qid=qid, source=source),
        difficulty=_require_inline(fields, "difficulty", qid=qid, source=source),
        tags=_parse_tags(fields["tags"][0], qid=qid, source=source),
        notes=_optional_inline(fields.get("notes", ("", ()))[0]),
    )


def _parse_fields(body: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Map each `**field:**` to its inline value and its following bullets."""
    fields: dict[str, tuple[str, tuple[str, ...]]] = {}
    matches = list(_FIELD.finditer(body))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        tail = body[match.end() : end]
        bullets = tuple(bullet.group(1).strip() for bullet in _BULLET.finditer(tail))
        fields[match.group(1)] = (match.group(2).strip(), bullets)
    return fields


def _require_inline(
    fields: dict[str, tuple[str, tuple[str, ...]]], name: str, *, qid: str, source: str
) -> str:
    value = fields[name][0]
    if not value:
        raise GoldenSetError(f"{source} {qid} has an empty {name}")
    return value


def _optional_inline(value: str) -> str | None:
    stripped = value.strip()
    return None if not stripped or stripped.lower() in _NONE_MARKERS else stripped


def _link_target(item: str, *, qid: str, source: str) -> str:
    """Accept either a bare URL or `[label](href)`, and return the href."""
    match = _MARKDOWN_LINK.match(item.strip())
    href = match.group("href") if match else item.strip()
    if not href.startswith("http"):
        raise GoldenSetError(f"{source} {qid} has a non-URL expected source: {item!r}")
    return href


def _parse_bool(value: str, *, qid: str, source: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "yes"}:
        return True
    if normalized in {"false", "no"}:
        return False
    raise GoldenSetError(f"{source} {qid} has a non-boolean expected_abstention: {value!r}")


def _parse_tags(value: str, *, qid: str, source: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for pair in value.split(","):
        item = pair.strip()
        if not item:
            continue
        key, separator, tag_value = item.partition("=")
        if not separator:
            raise GoldenSetError(f"{source} {qid} has a tag without a value: {item!r}")
        tags[key.strip()] = tag_value.strip()
    if not tags:
        raise GoldenSetError(f"{source} {qid} has no tags")
    return tags
