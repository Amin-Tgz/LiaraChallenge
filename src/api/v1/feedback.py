"""Resolution feedback API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.enums import FeedbackOutcome
from src.db.session import get_session
from src.services.feedback import record_faq_feedback

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    question: str = Field(min_length=1)
    outcome: FeedbackOutcome
    presented_faq_ids: list[uuid.UUID] = Field(min_length=1)
    note: str | None = None


class FeedbackResponse(BaseModel):
    feedback_id: uuid.UUID
    outcome: FeedbackOutcome
    rescue_tools_available: bool


@router.post("/feedback", response_model=FeedbackResponse)
async def create_feedback(
    payload: FeedbackRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackResponse:
    record = await record_faq_feedback(
        session,
        session_id=payload.session_id,
        conversation_id=payload.conversation_id,
        question=payload.question,
        outcome=payload.outcome,
        presented_faq_ids=payload.presented_faq_ids,
        note=payload.note,
    )
    return FeedbackResponse(
        feedback_id=record.feedback_id,
        outcome=record.outcome,
        rescue_tools_available=record.rescue_tools_available,
    )
