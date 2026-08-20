from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.db.models import AnonymousSession, FaqItem, UsageEvent
from src.db.models.enums import FaqStatus, RescueTool, UsageEventType
from src.db.session import get_session
from src.main import create_app
from src.services.interactions import record_faq_interaction

pytestmark = pytest.mark.asyncio


async def test_impressions_selections_and_rescue_transitions_are_queryable(
    migrated: AsyncConnection,
) -> None:
    session_id = uuid.uuid4()
    faq_ids = [uuid.uuid4(), uuid.uuid4()]
    question = f"interaction-{uuid.uuid4()}"
    await migrated.execute(AnonymousSession.__table__.insert().values(id=session_id))
    for faq_id in faq_ids:
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

    assert (
        await record_faq_interaction(
            migrated,
            event_type=UsageEventType.FAQ_IMPRESSION,
            session_id=session_id,
            question=question,
            faq_item_ids=faq_ids,
        )
        == 2
    )
    assert (
        await record_faq_interaction(
            migrated,
            event_type=UsageEventType.FAQ_SELECTION,
            session_id=session_id,
            question=question,
            faq_item_ids=[faq_ids[1]],
        )
        == 1
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
            "/api/v1/faq/interactions",
            json={
                "event_type": UsageEventType.RESCUE_TOOL_TRANSITION.value,
                "session_id": str(session_id),
                "question": question,
                "rescue_tool": RescueTool.CHAT.value,
            },
        )
    assert response.status_code == 200
    assert response.json() == {"recorded": 1}

    events = (
        await migrated.execute(
            select(UsageEvent)
            .where(UsageEvent.question == question)
            .order_by(UsageEvent.created_at)
        )
    ).all()
    assert [event.event_type for event in events].count("faq_impression") == 2
    assert [event.event_type for event in events].count("faq_selection") == 1
    transition = next(event for event in events if event.event_type == "rescue_tool_transition")
    assert transition.rescue_tool == "chat"
    assert transition.session_id == session_id
