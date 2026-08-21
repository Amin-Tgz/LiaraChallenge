from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.conversation import AnonymousSession, Conversation, RequestJob
from src.db.models.enums import JobStatus
from src.db.session import get_session
from src.main import create_app

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> tuple[AnonymousSession, Conversation]:
    anon = AnonymousSession(id=uuid.uuid4())
    conversation = Conversation(
        session=anon,
        initial_question="چطور برنامه را مستقر کنم؟",
        initial_question_normalized="چطور برنامه را مستقر کنم؟",
        technical_profile={},
    )
    session.add_all([anon, conversation])
    await session.flush()
    return anon, conversation


async def _client(
    db_session: AsyncSession,
    anon: AnonymousSession,
) -> httpx.AsyncClient:
    app = create_app()

    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={"rescue_session": str(anon.id)},
    )


async def test_owned_completed_conversation_is_deleted(db_session: AsyncSession) -> None:
    anon, conversation = await _seed(db_session)
    async with await _client(db_session, anon) as client:
        response = await client.delete(f"/api/v1/chat/conversations/{conversation.id}")

    assert response.status_code == 204
    assert await db_session.get(Conversation, conversation.id) is None


async def test_foreign_conversation_is_indistinguishable_from_missing(
    db_session: AsyncSession,
) -> None:
    _, conversation = await _seed(db_session)
    other = AnonymousSession(id=uuid.uuid4())
    db_session.add(other)
    await db_session.flush()

    async with await _client(db_session, other) as client:
        foreign = await client.delete(f"/api/v1/chat/conversations/{conversation.id}")
        missing = await client.delete(f"/api/v1/chat/conversations/{uuid.uuid4()}")

    assert foreign.status_code == missing.status_code == 400
    assert foreign.json() == missing.json()
    assert await db_session.get(Conversation, conversation.id) is not None


async def test_conversation_with_active_job_is_not_deleted(db_session: AsyncSession) -> None:
    anon, conversation = await _seed(db_session)
    db_session.add(
        RequestJob(
            conversation_id=conversation.id,
            idempotency_key=uuid.uuid4().hex,
            status=JobStatus.GENERATING,
            question=conversation.initial_question,
            transitions=[],
            max_attempts=3,
        )
    )
    await db_session.flush()

    async with await _client(db_session, anon) as client:
        response = await client.delete(f"/api/v1/chat/conversations/{conversation.id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONVERSATION_BUSY"
    assert (
        await db_session.scalar(select(Conversation.id).where(Conversation.id == conversation.id))
        == conversation.id
    )
