"""FAQ impression, selection, and rescue-transition events."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.enums import RescueTool, UsageEventType
from src.db.session import get_session
from src.services.interactions import record_faq_interaction

router = APIRouter(prefix="/faq", tags=["faq"])
InteractionType = Literal[
    UsageEventType.FAQ_IMPRESSION,
    UsageEventType.FAQ_SELECTION,
    UsageEventType.RESCUE_TOOL_TRANSITION,
]


class FaqInteractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: InteractionType
    session_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    question: str = Field(min_length=1)
    faq_item_ids: list[uuid.UUID] = Field(default_factory=list)
    rescue_tool: RescueTool | None = None


class FaqInteractionResponse(BaseModel):
    recorded: int


@router.post("/interactions", response_model=FaqInteractionResponse)
async def create_faq_interaction(
    payload: FaqInteractionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FaqInteractionResponse:
    recorded = await record_faq_interaction(
        session,
        event_type=payload.event_type,
        session_id=payload.session_id,
        conversation_id=payload.conversation_id,
        question=payload.question,
        faq_item_ids=payload.faq_item_ids,
        rescue_tool=payload.rescue_tool,
    )
    return FaqInteractionResponse(recorded=recorded)
