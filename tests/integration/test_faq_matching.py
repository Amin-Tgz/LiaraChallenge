from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.config import Settings
from src.db.models import FaqItem
from src.db.models.enums import FaqStatus
from src.services.embeddings import EmbeddingBatch
from src.services.faq import embed_faq_questions, match_faqs

pytestmark = pytest.mark.asyncio

DIMENSIONS = 1536


def _vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * (DIMENSIONS - 2))]


@dataclass
class StubEmbeddings:
    query_vector: list[float]
    batch_vectors: list[list[float]] = field(default_factory=list)
    one_inputs: list[str] = field(default_factory=list)
    batch_inputs: list[list[str]] = field(default_factory=list)

    def embed_one(self, text: str) -> list[float]:
        self.one_inputs.append(text)
        return self.query_vector

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        self.batch_inputs.append(list(texts))
        return EmbeddingBatch(
            vectors=self.batch_vectors,
            model="test-question-embedding-model",
            prompt_tokens=7,
            total_tokens=7,
        )


def _faq_values(
    *,
    question: str,
    priority: int,
    embedding: list[float] | None,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "question": question,
        "question_normalized": question,
        "answer": f"Answer for {question}",
        "source_url": "https://docs.liara.ir/paas/deploy",
        "heading_anchor": "deploy",
        "source_commit": "a" * 40,
        "status": FaqStatus.GENERATED.value,
        "is_active": True,
        "priority": priority,
        "tags": ["deploy"],
        "embedding_model": "text-embedding-3-large",
        "embedding_dimensions": DIMENSIONS,
        "embedding": embedding,
    }


async def test_pending_faq_questions_are_normalized_and_embedded_in_their_own_column(
    migrated: AsyncConnection,
) -> None:
    values = _faq_values(question="  LIARA   Deploy  ", priority=0, embedding=None)
    await migrated.execute(FaqItem.__table__.insert().values(**values))
    vector = _vector(1.0)
    embeddings = StubEmbeddings(query_vector=vector, batch_vectors=[vector])

    report = await embed_faq_questions(
        migrated,
        embeddings,
        faq_item_ids=[values["id"]],
    )

    stored = (await migrated.execute(select(FaqItem).where(FaqItem.id == values["id"]))).one()
    assert report.embedded == 1
    assert report.total_tokens == 7
    assert embeddings.batch_inputs == [["liara deploy"]]
    assert stored.question_normalized == "liara deploy"
    assert list(stored.embedding) == vector
    assert stored.embedding_model == "test-question-embedding-model"


async def test_faq_matching_suppresses_weak_results_and_preserves_semantic_similarity(
    migrated: AsyncConnection,
) -> None:
    exact = _faq_values(question="Exact semantic match", priority=0, embedding=_vector(1.0))
    curated = _faq_values(
        question="Curated lower semantic match",
        priority=30,
        embedding=_vector(0.8, math.sqrt(1 - 0.8**2)),
    )
    weak = _faq_values(
        question="Weak but highly curated match",
        priority=1000,
        embedding=_vector(0.0, 1.0),
    )
    await migrated.execute(FaqItem.__table__.insert(), [exact, curated, weak])
    embeddings = StubEmbeddings(query_vector=_vector(1.0))
    settings = Settings(
        _env_file=None,
        faq_similarity_threshold=0.4,
        faq_top_k=2,
        faq_priority_weight=0.01,
    )

    matches = await match_faqs(
        migrated,
        "  LIARA   Deploy  ",
        embeddings,
        settings=settings,
    )

    assert embeddings.one_inputs == ["liara deploy"]
    assert [match.faq_item_id for match in matches] == [curated["id"], exact["id"]]
    assert matches[0].similarity == pytest.approx(0.8)
    assert matches[0].ranking_score == pytest.approx(1.1)
    assert matches[0].citation_url == "https://docs.liara.ir/paas/deploy#deploy"
    assert weak["id"] not in {match.faq_item_id for match in matches}
    assert all(not hasattr(match, "distance") for match in matches)


async def test_short_ambiguous_query_uses_the_stronger_configured_threshold(
    migrated: AsyncConnection,
) -> None:
    celery = _faq_values(
        question="سلری چیست؟",
        priority=0,
        embedding=_vector(0.41, math.sqrt(1 - 0.41**2)),
    )
    await migrated.execute(FaqItem.__table__.insert().values(**celery))
    settings = Settings(
        _env_file=None,
        faq_similarity_threshold=0.4,
        faq_short_query_max_chars=8,
        faq_short_query_similarity_threshold=0.6,
    )

    matches = await match_faqs(
        migrated,
        "سلام",
        StubEmbeddings(query_vector=_vector(1.0)),
        settings=settings,
    )

    assert matches == []


async def test_equivalent_faq_questions_only_consume_one_result_slot(
    migrated: AsyncConnection,
) -> None:
    first = _faq_values(question="سلری چیست؟", priority=1, embedding=_vector(1.0))
    duplicate = _faq_values(question="سلری چیست؟", priority=0, embedding=_vector(1.0))
    distinct = _faq_values(
        question="ردیس چیست؟",
        priority=0,
        embedding=_vector(0.9, math.sqrt(1 - 0.9**2)),
    )
    await migrated.execute(FaqItem.__table__.insert(), [first, duplicate, distinct])
    settings = Settings(
        _env_file=None,
        faq_similarity_threshold=0.4,
        faq_top_k=2,
        faq_candidate_multiplier=3,
    )

    matches = await match_faqs(
        migrated,
        "سلری چطور کار می‌کند؟",
        StubEmbeddings(query_vector=_vector(1.0)),
        settings=settings,
    )

    assert [match.question for match in matches] == ["سلری چیست؟", "ردیس چیست؟"]
