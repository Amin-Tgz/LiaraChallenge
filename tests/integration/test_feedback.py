from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.db.models import AnonymousSession, FaqItem, Feedback
from src.db.models.enums import FaqStatus, FeedbackOutcome
from src.db.session import get_session
from src.main import create_app
from src.services.feedback import record_faq_feedback

pytestmark = pytest.mark.asyncio


async def test_resolved_and_unresolved_faq_feedback_are_queryable(
    migrated: AsyncConnection,
) -> None:
    session_id = uuid.uuid4()
    faq_ids = [uuid.uuid4(), uuid.uuid4()]
    await migrated.execute(AnonymousSession.__table__.insert().values(id=session_id))
    for position, faq_id in enumerate(faq_ids):
        await migrated.execute(
            FaqItem.__table__.insert().values(
                id=faq_id,
                question=f"Question {position}",
                question_normalized=f"question {position}",
                answer=f"Answer {position}",
                source_url=f"https://docs.liara.ir/paas/page-{position}",
                status=FaqStatus.GENERATED.value,
                is_active=True,
                priority=0,
                tags=[],
                embedding_model="text-embedding-3-large",
                embedding_dimensions=1536,
                embedding=None,
            )
        )

    question_prefix = f"feedback-{uuid.uuid4()}"
    resolved = await record_faq_feedback(
        migrated,
        session_id=session_id,
        question=f"{question_prefix} resolved",
        outcome=FeedbackOutcome.RESOLVED,
        presented_faq_ids=faq_ids,
    )
    unresolved = await record_faq_feedback(
        migrated,
        session_id=session_id,
        question=f"{question_prefix} unresolved",
        outcome=FeedbackOutcome.UNRESOLVED,
        presented_faq_ids=faq_ids,
    )

    rows = (
        await migrated.execute(
            select(Feedback)
            .where(Feedback.question.startswith(question_prefix))
            .order_by(Feedback.question)
        )
    ).all()
    assert resolved.rescue_tools_available is False
    assert unresolved.rescue_tools_available is True
    assert {row.outcome for row in rows} == {"resolved", "unresolved"}
    assert all(row.session_id == session_id for row in rows)
    assert all(row.presented_faq_ids == [str(faq_id) for faq_id in faq_ids] for row in rows)
    unresolved_row = next(row for row in rows if row.outcome == "unresolved")
    assert unresolved_row.question.endswith("unresolved")
    assert unresolved_row.question_normalized.endswith("unresolved")
    assert unresolved_row.source_urls == [
        "https://docs.liara.ir/paas/page-0",
        "https://docs.liara.ir/paas/page-1",
    ]


async def test_feedback_endpoint_persists_unresolved_gap_and_offers_rescue_tools(
    migrated: AsyncConnection,
) -> None:
    session_id = uuid.uuid4()
    faq_id = uuid.uuid4()
    await migrated.execute(AnonymousSession.__table__.insert().values(id=session_id))
    await migrated.execute(
        FaqItem.__table__.insert().values(
            id=faq_id,
            question="Related question",
            question_normalized="related question",
            answer="Documented answer",
            source_url="https://docs.liara.ir/paas/example",
            status=FaqStatus.GENERATED.value,
            is_active=True,
            priority=0,
            tags=[],
            embedding_model="text-embedding-3-large",
            embedding_dimensions=1536,
            embedding=None,
        )
    )

    async def override_session() -> AsyncIterator[AsyncConnection]:
        yield migrated

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/feedback",
            json={
                "session_id": str(session_id),
                "question": "هنوز جوابم را پیدا نکردم",
                "outcome": "unresolved",
                "presented_faq_ids": [str(faq_id)],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "unresolved"
    assert body["rescue_tools_available"] is True
    stored = (
        await migrated.execute(
            select(Feedback).where(Feedback.id == uuid.UUID(body["feedback_id"]))
        )
    ).one()
    assert stored.outcome == "unresolved"
    assert stored.presented_faq_ids == [str(faq_id)]
