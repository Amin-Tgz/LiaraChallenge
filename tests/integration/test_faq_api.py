from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from src.api.v1.faq import get_faq_embeddings
from src.db.models import FaqItem
from src.db.models.enums import FaqStatus
from src.db.session import get_session
from src.main import create_app
from src.services import faq

pytestmark = pytest.mark.asyncio

DIMENSIONS = 1536


class StubEmbeddings:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.inputs: list[str] = []

    def embed_one(self, text: str) -> list[float]:
        self.inputs.append(text)
        return self.vector


async def test_faq_search_is_synchronous_and_never_generates_an_answer(
    migrated: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vector = [1.0, *([0.0] * (DIMENSIONS - 1))]
    faq_id = uuid.uuid4()
    await migrated.execute(
        FaqItem.__table__.insert().values(
            id=faq_id,
            question="چطور برنامه را مستقر کنم؟",
            question_normalized="چطور برنامه را مستقر کنم؟",
            answer="برای استقرار از دستور liara deploy استفاده کنید.",
            source_url="https://docs.liara.ir/paas/deploy",
            heading_anchor="deploy",
            source_commit="a" * 40,
            status=FaqStatus.GENERATED.value,
            is_active=True,
            priority=0,
            tags=["deploy"],
            embedding_model="text-embedding-3-large",
            embedding_dimensions=DIMENSIONS,
            embedding=vector,
        )
    )
    embeddings = StubEmbeddings(vector)

    def generation_must_not_run(*args: object, **kwargs: object) -> str:
        raise AssertionError("the synchronous FAQ search invoked an answer-generation model")

    monkeypatch.setattr(faq.GatewayFaqGenerator, "generate", generation_must_not_run)

    async def override_session() -> AsyncIterator[AsyncConnection]:
        yield migrated

    def override_embeddings() -> StubEmbeddings:
        return embeddings

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_faq_embeddings] = override_embeddings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/faq/search",
            json={"question": "  چطور   برنامه را مستقر کنم؟  "},
        )

    assert response.status_code == 200
    body = response.json()
    assert embeddings.inputs == ["چطور برنامه را مستقر کنم?"]
    assert body["rescue_tools_available"] is False
    assert len(body["results"]) == 1
    assert body["results"][0]["faq_item_id"] == str(faq_id)
    assert body["results"][0]["similarity"] == pytest.approx(1.0)
    assert body["results"][0]["source_url"].endswith("/paas/deploy#deploy")
