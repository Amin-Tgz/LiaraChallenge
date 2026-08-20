from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.db.models import AnonymousSession, Conversation
from src.services.technical_profile import update_conversation_technical_profile

pytestmark = pytest.mark.asyncio


async def test_runtime_stated_once_is_reused_on_a_later_turn(
    migrated: AsyncConnection,
) -> None:
    session_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    await migrated.execute(AnonymousSession.__table__.insert().values(id=session_id))
    await migrated.execute(
        Conversation.__table__.insert().values(
            id=conversation_id,
            session_id=session_id,
            initial_question="پروژهٔ من با Python اجرا می‌شود.",
            initial_question_normalized="پروژه من با python اجرا می شود.",
            technical_profile={},
        )
    )

    first_turn = await update_conversation_technical_profile(
        migrated,
        conversation_id,
        "runtime پروژهٔ من Python است و می‌خواهم deploy کنم.",
    )
    second_turn = await update_conversation_technical_profile(
        migrated,
        conversation_id,
        "حالا متغیر محیطی را کجا ثبت کنم؟",
    )

    assert first_turn["runtime"] == "python"
    assert first_turn["current_goal"] == "deploy"
    assert second_turn["runtime"] == "python"
    assert second_turn["current_goal"] == "deploy"
    stored = (
        await migrated.execute(
            select(Conversation.technical_profile).where(Conversation.id == conversation_id)
        )
    ).scalar_one()
    assert stored == second_turn
