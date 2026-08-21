"""Persist resolution feedback as queryable documentation-gap data."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models import AnonymousSession, Conversation, FaqItem, Feedback, Message, UsageEvent
from src.db.models.enums import (
    FeedbackOutcome,
    FeedbackReason,
    FeedbackStage,
    MessageRole,
    UsageEventType,
)

logger = get_logger(__name__)
Executor = AsyncSession | AsyncConnection


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    feedback_id: uuid.UUID
    outcome: FeedbackOutcome
    rescue_tools_available: bool


async def record_faq_feedback(
    executor: Executor,
    *,
    session_id: uuid.UUID,
    question: str,
    outcome: FeedbackOutcome,
    presented_faq_ids: Sequence[uuid.UUID],
    conversation_id: uuid.UUID | None = None,
    note: str | None = None,
) -> FeedbackRecord:
    normalized = normalize_query(question)
    if not normalized:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="feedback question is empty")
    if not presented_faq_ids:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail="FAQ feedback must name at least one presented entry",
        )

    try:
        session_exists = (
            await executor.execute(
                select(AnonymousSession.id).where(AnonymousSession.id == session_id)
            )
        ).scalar_one_or_none()
        if session_exists is None:
            raise RescueError(ErrorCode.INVALID_REQUEST, detail="feedback session does not exist")

        if conversation_id is not None:
            conversation_exists = (
                await executor.execute(
                    select(Conversation.id).where(
                        Conversation.id == conversation_id,
                        Conversation.session_id == session_id,
                    )
                )
            ).scalar_one_or_none()
            if conversation_exists is None:
                raise RescueError(
                    ErrorCode.INVALID_REQUEST,
                    detail="feedback conversation does not belong to the session",
                )

        faq_rows = (
            await executor.execute(
                select(FaqItem.id, FaqItem.source_url).where(FaqItem.id.in_(presented_faq_ids))
            )
        ).all()
        source_by_id = {row.id: row.source_url for row in faq_rows}
        missing = [faq_id for faq_id in presented_faq_ids if faq_id not in source_by_id]
        if missing:
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail=f"feedback names {len(missing)} unknown FAQ entries",
            )

        feedback_id = uuid.uuid4()
        await executor.execute(
            Feedback.__table__.insert().values(
                id=feedback_id,
                session_id=session_id,
                conversation_id=conversation_id,
                stage=FeedbackStage.FAQ.value,
                outcome=outcome.value,
                question=question,
                question_normalized=normalized,
                presented_faq_ids=[str(faq_id) for faq_id in presented_faq_ids],
                source_urls=list(
                    dict.fromkeys(source_by_id[faq_id] for faq_id in presented_faq_ids)
                ),
                note=note,
            )
        )
        # Resolution is an analytics signal in addition to the durable feedback
        # record. Keep it in the same transaction so the dashboard cannot drift.
        await executor.execute(
            UsageEvent.__table__.insert().values(
                event_type=UsageEventType.FAQ_RESOLUTION.value,
                session_id=session_id,
                conversation_id=conversation_id,
                question=question,
                payload={
                    "outcome": outcome.value,
                    "presented_faq_ids": [str(faq_id) for faq_id in presented_faq_ids],
                    "source_urls": list(
                        dict.fromkeys(source_by_id[faq_id] for faq_id in presented_faq_ids)
                    ),
                },
            )
        )
    except RescueError:
        raise
    except SQLAlchemyError as err:
        raise RescueError(
            ErrorCode.INTERNAL_ERROR,
            detail="database failed while persisting FAQ feedback",
        ) from err

    unresolved = outcome is FeedbackOutcome.UNRESOLVED
    logger.info(
        "FAQ resolution feedback persisted",
        extra={
            "feedback_id": str(feedback_id),
            "session_id": str(session_id),
            "conversation_id": str(conversation_id) if conversation_id else None,
            "outcome": outcome.value,
            "presented_count": len(presented_faq_ids),
            "documentation_gap": unresolved,
        },
    )
    return FeedbackRecord(
        feedback_id=feedback_id,
        outcome=outcome,
        rescue_tools_available=unresolved,
    )


async def record_chat_feedback(
    executor: Executor,
    *,
    session_id: uuid.UUID,
    message_id: uuid.UUID,
    outcome: FeedbackOutcome,
    reason: FeedbackReason | None = None,
    note: str | None = None,
) -> FeedbackRecord:
    """Persist a judgement on one assistant answer.

    The caller supplies only the verdict. Everything that makes the verdict
    analyzable — which question was asked, which documentation pages the answer
    leaned on — is read from the message itself, because a client that has to
    assemble that is a client that can get it wrong or omit it.

    The documentation pages come from the answer's own citations. That is what
    turns a thumbs-down into "this page produces bad answers", which is the only
    form of this signal anyone can act on.
    """
    try:
        message = (
            await executor.execute(
                select(Message)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Message.id == message_id,
                    Message.role == MessageRole.ASSISTANT.value,
                    Conversation.session_id == session_id,
                )
            )
        ).scalar_one_or_none()
        if message is None:
            # One refusal for "no such message", "not an answer", and "not
            # yours" — the differences are useful only to someone probing.
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail="feedback names no assistant message belonging to this session",
            )

        question = await _question_for(executor, message)
        source_urls = _cited_urls(message.citations)

        feedback_id = uuid.uuid4()
        await executor.execute(
            Feedback.__table__.insert().values(
                id=feedback_id,
                session_id=session_id,
                conversation_id=message.conversation_id,
                message_id=message_id,
                stage=FeedbackStage.CHAT.value,
                outcome=outcome.value,
                reason=reason.value if reason is not None else None,
                question=question,
                question_normalized=normalize_query(question),
                presented_faq_ids=[],
                source_urls=source_urls,
                note=note,
            )
        )
        # Same transaction as the feedback row, so the dashboard and the durable
        # record can never disagree about what was said.
        await executor.execute(
            UsageEvent.__table__.insert().values(
                event_type=UsageEventType.CHAT_RESOLUTION.value,
                session_id=session_id,
                conversation_id=message.conversation_id,
                question=question,
                payload={
                    "outcome": outcome.value,
                    "reason": reason.value if reason is not None else None,
                    "message_id": str(message_id),
                    "source_urls": source_urls,
                },
            )
        )
    except RescueError:
        raise
    except SQLAlchemyError as err:
        raise RescueError(
            ErrorCode.INTERNAL_ERROR,
            detail="database failed while persisting chat feedback",
        ) from err

    unresolved = outcome is FeedbackOutcome.UNRESOLVED
    logger.info(
        "chat answer feedback persisted",
        extra={
            "feedback_id": str(feedback_id),
            "session_id": str(session_id),
            "message_id": str(message_id),
            "outcome": outcome.value,
            "reason": reason.value if reason is not None else None,
            "cited_page_count": len(source_urls),
            "documentation_gap": unresolved,
        },
    )
    return FeedbackRecord(
        feedback_id=feedback_id,
        outcome=outcome,
        rescue_tools_available=unresolved,
    )


async def _question_for(executor: Executor, message: Message) -> str:
    """The user turn this answer replied to.

    Falls back to the conversation's opening question: an answer always has one
    of the two, and feedback with no question attached cannot be grouped with
    anything.
    """
    asked = (
        await executor.execute(
            select(Message.content)
            .where(
                Message.conversation_id == message.conversation_id,
                Message.role == MessageRole.USER.value,
                Message.ordinal < message.ordinal,
            )
            .order_by(Message.ordinal.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if asked:
        return str(asked)
    opening = (
        await executor.execute(
            select(Conversation.initial_question).where(Conversation.id == message.conversation_id)
        )
    ).scalar_one_or_none()
    return str(opening or "")


def _cited_urls(citations: Any) -> list[str]:
    """Distinct documentation URLs an answer cited, in the order it cited them."""
    if not isinstance(citations, list):
        return []
    urls = [
        citation["url"]
        for citation in citations
        if isinstance(citation, dict) and isinstance(citation.get("url"), str)
    ]
    return list(dict.fromkeys(urls))
