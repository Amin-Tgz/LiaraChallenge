"""Synchronous FAQ fast path; query embedding is its only model usage."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.services.embeddings import EmbeddingClient
from src.services.faq import FaqEmbeddingProvider, match_faqs

router = APIRouter(prefix="/faq", tags=["faq"])


class FaqSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


class FaqSearchResult(BaseModel):
    faq_item_id: uuid.UUID
    question: str
    answer: str
    similarity: float
    source_url: str
    source_commit: str | None
    tags: list[str]


class FaqSearchResponse(BaseModel):
    results: list[FaqSearchResult]
    rescue_tools_available: bool


async def get_faq_embeddings() -> AsyncIterator[EmbeddingClient]:
    client = EmbeddingClient()
    try:
        yield client
    finally:
        client.close()


@router.post("/search", response_model=FaqSearchResponse)
async def search_faq(
    payload: FaqSearchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    embeddings: Annotated[FaqEmbeddingProvider, Depends(get_faq_embeddings)],
) -> FaqSearchResponse:
    matches = await match_faqs(session, payload.question, embeddings)
    return FaqSearchResponse(
        results=[
            FaqSearchResult(
                faq_item_id=match.faq_item_id,
                question=match.question,
                answer=match.answer,
                similarity=match.similarity,
                source_url=match.citation_url,
                source_commit=match.source_commit,
                tags=match.tags,
            )
            for match in matches
        ],
        rescue_tools_available=not matches,
    )
