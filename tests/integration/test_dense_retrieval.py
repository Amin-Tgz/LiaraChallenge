"""Dense retrieval against the real active pgvector index."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.config import get_settings
from src.db.models import DocumentChunk, IndexVersion
from src.services.retrieval import dense_retrieve

pytestmark = pytest.mark.asyncio


@dataclass
class StubEmbeddings:
    vector: list[float]
    inputs: list[str] = field(default_factory=list)

    def embed_one(self, text: str) -> list[float]:
        self.inputs.append(text)
        return self.vector


async def test_dense_retrieval_is_active_scoped_and_returns_complete_evidence(
    migrated: AsyncConnection,
) -> None:
    active = (
        await migrated.execute(
            select(IndexVersion.id, IndexVersion.source_commit).where(
                IndexVersion.is_active.is_(True)
            )
        )
    ).one_or_none()
    if active is None:
        pytest.skip("full ingestion has not activated an index")

    seed = (
        await migrated.execute(
            select(DocumentChunk.embedding)
            .where(
                DocumentChunk.index_version_id == active.id,
                DocumentChunk.embedding.is_not(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if seed is None:
        pytest.fail("the active index has no embedded chunks")

    embeddings = StubEmbeddings(vector=list(seed))
    results = await dense_retrieve(
        migrated,
        "  LIARA   deploy  ",
        embeddings,
        top_k=get_settings().retrieval_top_k,
    )

    assert embeddings.inputs == ["liara deploy"]
    assert results
    assert all(result.index_version_id == active.id for result in results)
    assert all(result.source_commit == active.source_commit for result in results)

    result = results[0]
    assert result.similarity == pytest.approx(1.0)
    assert result.text
    assert result.source_url.startswith("https://")
    assert result.citation_url == (
        f"{result.source_url}#{result.heading_anchor}"
        if result.heading_anchor
        else result.source_url
    )
    assert {
        "source_path",
        "section_title",
        "breadcrumbs",
        "content_type",
        "code_languages",
        "service",
        "runtime",
        "framework",
        "language",
    } <= result.metadata.keys()
    assert isinstance(result.images, list)
