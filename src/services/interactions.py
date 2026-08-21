"""Durable FAQ interaction signals for ranking and analytics."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models import AnonymousSession, Conversation, FaqItem, UsageEvent
from src.db.models.enums import RescueTool, UsageEventType

logger = get_logger(__name__)
Executor = AsyncSession | AsyncConnection
FAQ_INTERACTION_TYPES = frozenset({UsageEventType.FAQ_IMPRESSION, UsageEventType.FAQ_SELECTION})

#: Marks the one row per search, as distinct from the one row per shown entry
#: that `record_faq_interaction` writes. Queries that want to count questions
#: rather than results filter on it.
SEARCH_MARKER = "result_count"

#: Payload key holding the output of `normalize_query`. Named here, beside the
#: only code that writes it, so a reader cannot guess at a different spelling.
NORMALIZED_QUESTION_KEY = "question_normalized"


async def record_faq_interaction(
    executor: Executor,
    *,
    event_type: UsageEventType,
    session_id: uuid.UUID,
    question: str,
    faq_item_ids: Sequence[uuid.UUID] = (),
    conversation_id: uuid.UUID | None = None,
    rescue_tool: RescueTool | None = None,
) -> int:
    """Record one row per FAQ shown/selected, or one rescue transition row."""
    normalized = normalize_query(question)
    if not normalized:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="interaction question is empty")
    if event_type in FAQ_INTERACTION_TYPES and not faq_item_ids:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail=f"{event_type.value} must name at least one FAQ entry",
        )
    if event_type is UsageEventType.FAQ_SELECTION and len(faq_item_ids) != 1:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail="FAQ selection must name exactly one entry",
        )
    if event_type is UsageEventType.RESCUE_TOOL_TRANSITION and rescue_tool is None:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail="rescue transition must name the selected tool",
        )
    if event_type not in FAQ_INTERACTION_TYPES | {UsageEventType.RESCUE_TOOL_TRANSITION}:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail=f"unsupported FAQ interaction type {event_type.value}",
        )

    try:
        session_exists = (
            await executor.execute(
                select(AnonymousSession.id).where(AnonymousSession.id == session_id)
            )
        ).scalar_one_or_none()
        if session_exists is None:
            raise RescueError(
                ErrorCode.INVALID_REQUEST, detail="interaction session does not exist"
            )
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
                    detail="interaction conversation does not belong to the session",
                )
        if faq_item_ids:
            known_ids = set(
                (await executor.execute(select(FaqItem.id).where(FaqItem.id.in_(faq_item_ids))))
                .scalars()
                .all()
            )
            if known_ids != set(faq_item_ids):
                raise RescueError(
                    ErrorCode.INVALID_REQUEST,
                    detail="interaction names an unknown FAQ entry",
                )

        ids: Sequence[uuid.UUID | None] = faq_item_ids or (None,)
        await executor.execute(
            UsageEvent.__table__.insert(),
            [
                {
                    "event_type": event_type.value,
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "faq_item_id": faq_item_id,
                    "rescue_tool": rescue_tool.value if rescue_tool else None,
                    "question": question,
                    "payload": {NORMALIZED_QUESTION_KEY: normalized},
                }
                for faq_item_id in ids
            ],
        )
    except RescueError:
        raise
    except SQLAlchemyError as err:
        raise RescueError(
            ErrorCode.INTERNAL_ERROR,
            detail="database failed while recording FAQ interaction",
        ) from err
    return len(ids)


async def record_faq_search(
    executor: Executor,
    *,
    session_id: uuid.UUID | None,
    question: str,
    result_count: int,
    similarity_threshold: float,
) -> None:
    """Record that a search happened, including one that matched nothing.

    Impressions are written per shown entry and only when something was shown,
    so they cannot answer either of the two questions an operator actually has
    after moving a threshold: how many searches there were, and how many of them
    returned anything. This row is the denominator for both.

    Never raises. A search that succeeded must not fail because its analytics
    row could not be written.
    """
    normalized = normalize_query(question)
    if not normalized:
        return
    try:
        await executor.execute(
            UsageEvent.__table__.insert().values(
                event_type=UsageEventType.FAQ_IMPRESSION.value,
                session_id=session_id,
                question=question,
                payload={
                    NORMALIZED_QUESTION_KEY: normalized,
                    SEARCH_MARKER: result_count,
                    "similarity_threshold": similarity_threshold,
                },
            )
        )
    except SQLAlchemyError as err:
        logger.warning(
            "could not record FAQ search; the search itself was unaffected",
            extra={"cause": type(err).__name__},
        )
