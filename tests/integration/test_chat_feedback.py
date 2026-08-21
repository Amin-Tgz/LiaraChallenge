"""Chat-stage feedback: a verdict on one answer, joined to the pages behind it.

The point of these tests is the join. A thumbs-down that records only "bad"
tells an operator nothing; one that records which documentation pages the
rejected answer cited is what makes "this page produces bad answers" a query
rather than a guess. So what is asserted throughout is that the record carries
the question and the cited pages *without the client supplying either*.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.errors import ErrorCode, RescueError
from src.db.models import AnonymousSession, Conversation, Feedback, Message, UsageEvent
from src.db.models.enums import (
    FeedbackOutcome,
    FeedbackReason,
    FeedbackStage,
    MessageRole,
    UsageEventType,
)
from src.services.feedback import record_chat_feedback

pytestmark = pytest.mark.asyncio

CITED = [
    {
        "evidence_id": "chunk:1",
        "url": "https://docs.liara.ir/paas/django/deploy",
        "page_title": "استقرار جنگو",
        "section_title": "Deploy",
        "source_commit": "abc123",
    },
    {
        "evidence_id": "chunk:2",
        "url": "https://docs.liara.ir/paas/django/env",
        "page_title": "متغیرهای محیطی",
        "section_title": None,
        "source_commit": "abc123",
    },
]


async def _conversation(
    conn: AsyncConnection,
    *,
    question: str = "چطور جنگو را روی لیارا مستقر کنم؟",
    citations: list[dict] | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """One session with a two-turn conversation. Returns (session, conv, answer)."""
    session_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    answer_id = uuid.uuid4()
    await conn.execute(AnonymousSession.__table__.insert().values(id=session_id))
    await conn.execute(
        Conversation.__table__.insert().values(
            id=conversation_id,
            session_id=session_id,
            initial_question=question,
            initial_question_normalized=question,
            technical_profile={},
        )
    )
    await conn.execute(
        Message.__table__.insert().values(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            ordinal=0,
            role=MessageRole.USER.value,
            content=question,
            citations=[],
            images=[],
        )
    )
    await conn.execute(
        Message.__table__.insert().values(
            id=answer_id,
            conversation_id=conversation_id,
            ordinal=1,
            role=MessageRole.ASSISTANT.value,
            content="پاسخ مستند",
            citations=CITED if citations is None else citations,
            images=[],
        )
    )
    return session_id, conversation_id, answer_id


async def test_the_cited_pages_come_from_the_answer_not_from_the_client(
    migrated: AsyncConnection,
) -> None:
    session_id, conversation_id, answer_id = await _conversation(migrated)

    record = await record_chat_feedback(
        migrated,
        session_id=session_id,
        message_id=answer_id,
        outcome=FeedbackOutcome.UNRESOLVED,
        reason=FeedbackReason.INCOMPLETE,
    )

    row = (await migrated.execute(select(Feedback).where(Feedback.id == record.feedback_id))).one()
    assert row.stage == FeedbackStage.CHAT.value
    assert row.outcome == FeedbackOutcome.UNRESOLVED.value
    assert row.reason == FeedbackReason.INCOMPLETE.value
    assert row.message_id == answer_id
    assert row.conversation_id == conversation_id
    # Neither of these was passed in.
    assert row.question == "چطور جنگو را روی لیارا مستقر کنم؟"
    assert row.source_urls == [
        "https://docs.liara.ir/paas/django/deploy",
        "https://docs.liara.ir/paas/django/env",
    ]


async def test_the_dashboard_event_lands_in_the_same_transaction(
    migrated: AsyncConnection,
) -> None:
    session_id, conversation_id, answer_id = await _conversation(migrated)

    await record_chat_feedback(
        migrated,
        session_id=session_id,
        message_id=answer_id,
        outcome=FeedbackOutcome.RESOLVED,
    )

    event = (
        await migrated.execute(
            select(UsageEvent).where(
                UsageEvent.conversation_id == conversation_id,
                UsageEvent.event_type == UsageEventType.CHAT_RESOLUTION.value,
            )
        )
    ).one()
    assert event.payload["outcome"] == FeedbackOutcome.RESOLVED.value
    assert event.payload["reason"] is None
    assert event.payload["source_urls"] == [
        "https://docs.liara.ir/paas/django/deploy",
        "https://docs.liara.ir/paas/django/env",
    ]


async def test_an_abstention_with_no_citations_is_still_recordable(
    migrated: AsyncConnection,
) -> None:
    """An answer that abstained cites nothing, and is exactly what users reject."""
    session_id, _, answer_id = await _conversation(migrated, citations=[])

    record = await record_chat_feedback(
        migrated,
        session_id=session_id,
        message_id=answer_id,
        outcome=FeedbackOutcome.UNRESOLVED,
        reason=FeedbackReason.IRRELEVANT,
    )

    row = (await migrated.execute(select(Feedback).where(Feedback.id == record.feedback_id))).one()
    assert row.source_urls == []


async def test_feedback_on_someone_elses_answer_is_refused(
    migrated: AsyncConnection,
) -> None:
    _, _, answer_id = await _conversation(migrated)
    stranger = uuid.uuid4()
    await migrated.execute(AnonymousSession.__table__.insert().values(id=stranger))

    with pytest.raises(RescueError) as failure:
        await record_chat_feedback(
            migrated,
            session_id=stranger,
            message_id=answer_id,
            outcome=FeedbackOutcome.UNRESOLVED,
        )
    assert failure.value.code is ErrorCode.INVALID_REQUEST


async def test_feedback_on_a_user_turn_is_refused(migrated: AsyncConnection) -> None:
    """Only answers are judged. Rating your own question is meaningless data."""
    session_id, conversation_id, _ = await _conversation(migrated)
    user_turn = (
        await migrated.execute(
            select(Message.id).where(
                Message.conversation_id == conversation_id,
                Message.role == MessageRole.USER.value,
            )
        )
    ).scalar_one()

    with pytest.raises(RescueError):
        await record_chat_feedback(
            migrated,
            session_id=session_id,
            message_id=user_turn,
            outcome=FeedbackOutcome.RESOLVED,
        )


async def test_an_unknown_message_is_refused_the_same_way_as_a_foreign_one(
    migrated: AsyncConnection,
) -> None:
    session_id, _, _ = await _conversation(migrated)

    with pytest.raises(RescueError) as failure:
        await record_chat_feedback(
            migrated,
            session_id=session_id,
            message_id=uuid.uuid4(),
            outcome=FeedbackOutcome.RESOLVED,
        )
    assert failure.value.code is ErrorCode.INVALID_REQUEST
