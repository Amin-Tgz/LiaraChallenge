"""Structural guard: one normalizer, used by both sides.

Index-time and query-time normalization must be the *same code*. If one path
grows its own folding — a stray `.replace()` table, a second `maketrans`, a
"quick" lowercase before a query — nothing raises and nothing logs. Recall just
drops, and no test that exercises a single path can see it.

So this file tests the source tree rather than behavior: a second normalizer
cannot appear, and a module that stores or queries normalized text cannot do so
without going through the shared function.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
NORMALIZER_MODULE = SRC / "core" / "normalization.py"

#: Where normalized values are produced and consumed. Model modules are exempt:
#: they declare the columns, they do not fill them.
PRODUCING_PACKAGES = ("services", "api", "mcp")

#: Building blocks of a text-folding implementation. Their presence outside the
#: normalizer is the signature of a second one.
FOLDING_CALLS = {"maketrans", "translate", "casefold"}


def _python_files(*relative: str) -> list[Path]:
    roots = [SRC / part for part in relative] if relative else [SRC]
    return [
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _imports_the_normalizer(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("core.normalization"):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name.endswith("core.normalization") for alias in node.names
        ):
            return True
    return False


def test_the_normalizer_module_exists_where_everything_expects_it() -> None:
    assert NORMALIZER_MODULE.exists(), "the single normalization module was moved or removed"


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p))
def test_no_second_normalizer_is_defined(path: Path) -> None:
    if path == NORMALIZER_MODULE:
        return
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            assert name not in FOLDING_CALLS, (
                f"{path.name} folds text itself ({name}); index-time and query-time "
                "normalization must both call src.core.normalization.normalize_text"
            )
        if isinstance(node, ast.Attribute) and node.attr == "normalize":
            value = node.value
            assert getattr(value, "id", None) != "unicodedata", (
                f"{path.name} runs its own Unicode normalization; that belongs in "
                "src/core/normalization.py so both paths share one definition"
            )


@pytest.mark.parametrize("path", _python_files(*PRODUCING_PACKAGES), ids=lambda p: str(p))
def test_modules_handling_normalized_text_use_the_shared_function(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if "_normalized" not in source:
        return
    tree = ast.parse(source)
    assert _imports_the_normalizer(tree), (
        f"{path.name} reads or writes normalized text without importing "
        "src.core.normalization — the index path and the query path would drift"
    )
