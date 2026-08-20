"""Literal retrieval over the real normalized Liara corpus."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from src.services.retrieval import RetrievalIntent, lexical_retrieve

pytestmark = pytest.mark.asyncio


async def test_exact_error_string_is_found(migrated: AsyncConnection) -> None:
    results = await lexical_retrieve(
        migrated,
        "Error: Audio file AUDIO_FILE not found",
    )

    assert results
    assert results[0].metadata["source_path"] == "src/pages/ai/foundations/prompts.mdx"
    assert "Error: Audio file '$AUDIO_FILE' not found" in results[0].text
    assert results[0].lexical_score > 0


async def test_command_name_is_found(migrated: AsyncConnection) -> None:
    results = await lexical_retrieve(migrated, "LIARA deploy")

    assert results
    assert any("liara deploy" in result.text.lower() for result in results)
    assert all(result.source_commit for result in results)
    assert all(result.citation_url.startswith("https://") for result in results)


async def test_only_explicit_intent_hard_filters_real_results(
    migrated: AsyncConnection,
) -> None:
    soft = await lexical_retrieve(
        migrated,
        "liara deploy",
        top_k=20,
        intent=RetrievalIntent(profile_hints={"runtime": "python"}),
    )
    explicit = await lexical_retrieve(
        migrated,
        "liara deploy",
        top_k=20,
        intent=RetrievalIntent(explicit_filters={"runtime": "nodejs"}),
    )

    assert soft
    assert any(result.metadata["runtime"] != "python" for result in soft)
    assert explicit
    assert all(result.metadata["runtime"] == "nodejs" for result in explicit)
