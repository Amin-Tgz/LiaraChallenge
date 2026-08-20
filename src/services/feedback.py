"""Persist resolution feedback as queryable documentation-gap data."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models import AnonymousSession, Conversation, FaqItem, Feedback, UsageEvent
from src.db.models.enums import FeedbackOutcome, FeedbackStage, UsageEventType

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
