"""Ingest scope is configuration, and must behave like it.

Narrowing the corpus is the schedule's pressure valve: if it required a code
change it would be a refactor under time pressure, which is exactly when nobody
wants one.
"""

from __future__ import annotations

import pytest

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.services.ingestion.repository import (
    Checkout,
    content_hash,
    discover_documents,
    in_scope,
    section_of,
)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/pages/paas/about.mdx", True),
        ("src/pages/dbaas/postgresql/about.mdx", True),
        # Not content: Next.js plumbing and non-MDX files share the tree.
        ("src/pages/_app.js", False),
        ("src/pages/index.js", False),
        ("src/components/Common/tabs.js", False),
        ("README.md", False),
    ],
)
def test_only_mdx_under_the_content_root_is_content(path: str, expected: bool) -> None:
    assert in_scope(path, _settings()) is expected


def test_section_allowlist_narrows_without_code_change() -> None:
    narrowed = _settings(ingest_sections="paas,dbaas")
    assert in_scope("src/pages/paas/about.mdx", narrowed)
    assert in_scope("src/pages/dbaas/about.mdx", narrowed)
    assert not in_scope("src/pages/ai/cookbook/rag.mdx", narrowed)
    assert not in_scope("src/pages/tv/about.mdx", narrowed)


def test_wildcard_means_everything() -> None:
    everything = _settings(ingest_sections="*")
    assert in_scope("src/pages/ai/cookbook/rag.mdx", everything)


def test_exclude_globs_apply_to_both_path_forms() -> None:
    excluded = _settings(ingest_exclude_globs="ai/ai-sdk-*/**,**/changelog.mdx")
    assert not in_scope("src/pages/ai/ai-sdk-core/overview.mdx", excluded)
    assert not in_scope("src/pages/paas/changelog.mdx", excluded)
    assert in_scope("src/pages/ai/cookbook/rag.mdx", excluded)


@pytest.mark.parametrize(
    ("path", "section"),
    [
        ("src/pages/paas/django/create-app.mdx", "paas"),
        ("src/pages/references/cli/add-account.mdx", "references"),
        # A file directly under the content root belongs to no section; calling
        # it "index" would invent one.
        ("src/pages/index.mdx", "overview"),
    ],
)
def test_section_of(path: str, section: str) -> None:
    assert section_of(path) == section


def test_content_hash_is_content_only() -> None:
    assert content_hash("same") == content_hash("same")
    assert content_hash("same") != content_hash("different")


def _write(tmp_path, relative: str, body: str) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_discover_reads_only_in_scope_documents(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write(tmp_path, "src/pages/paas/about.mdx", "# paas")
    _write(tmp_path, "src/pages/ai/rag.mdx", "# ai")
    _write(tmp_path, "src/pages/_app.js", "export default 1")

    checkout = Checkout(path=tmp_path, commit="a" * 40, repo_url="https://x/y", branch="master")
    found = discover_documents(checkout, _settings(ingest_sections="paas"))

    assert [d.source_path for d in found] == ["src/pages/paas/about.mdx"]
    assert found[0].section == "paas"
    assert found[0].content_hash == content_hash("# paas")


def test_scope_matching_nothing_is_an_error_not_an_empty_index(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Silently building an empty index would pass every downstream check."""
    _write(tmp_path, "src/pages/paas/about.mdx", "# paas")
    checkout = Checkout(path=tmp_path, commit="a" * 40, repo_url="https://x/y", branch="master")

    with pytest.raises(RescueError) as caught:
        discover_documents(checkout, _settings(ingest_sections="nonexistent"))
    assert caught.value.code is ErrorCode.INGESTION_SOURCE_UNAVAILABLE
