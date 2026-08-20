from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.errors import ErrorCode
from src.db.models import Document, DocumentChunk, FaqItem, IndexVersion, UsageEvent
from src.services.faq import generate_document_faqs

pytestmark = pytest.mark.asyncio


class MixedGenerator:
    def __init__(self, question: str) -> None:
        self.question = question
        self.calls = 0

    def generate(self, *, title: str, chunks: list[dict]) -> str:
        self.calls += 1
        ordinal = chunks[0]["ordinal"]
        return json.dumps(
            {
                "faqs": [
                    {
                        "question": self.question,
                        "answer": "این پاسخ معتبر و مستقیماً متکی بر مستندات لیارا است.",
                        "chunk_ordinal": ordinal,
                        "tags": ["test"],
                    },
                    {
                        "question": "",
                        "answer": "bad",
                        "chunk_ordinal": ordinal,
                        "tags": [],
                    },
                ]
            },
            ensure_ascii=False,
        )


async def test_malformed_faq_is_recorded_and_run_continues(
    migrated: AsyncConnection,
) -> None:
    document_id = (
        await migrated.execute(
            select(Document.id)
            .join(IndexVersion, IndexVersion.id == Document.index_version_id)
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(IndexVersion.is_active.is_(True))
            .limit(1)
        )
    ).scalar_one()
    question = f"پرسش معتبر آزمایشی {uuid.uuid4()} چیست؟"
    generator = MixedGenerator(question)

    report = await generate_document_faqs(migrated, document_id, generator)

    assert report.accepted == 1
    assert report.rejected == 1
    assert generator.calls == 1
    stored = (await migrated.execute(select(FaqItem).where(FaqItem.question == question))).one()
    assert stored.source_document_id == document_id
    assert stored.source_chunk_id is not None
    assert stored.source_url.startswith("https://")
    assert stored.embedding is None
    rejected = (
        await migrated.execute(
            select(func.count())
            .select_from(UsageEvent)
            .where(ErrorCode.FAQ_OUTPUT_INVALID.value == UsageEvent.error_code)
        )
    ).scalar_one()
    assert rejected >= 1

    second = await generate_document_faqs(migrated, document_id, generator)
    assert second.skipped is True
    assert generator.calls == 1
