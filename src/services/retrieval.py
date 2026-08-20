"""Shared documentation retrieval primitives.

This module is the one retrieval core used by chat, MCP, and the Skill-facing
API.  Dense search is deliberately scoped to the active index in the same SQL
statement that ranks chunks, so a superseded or failed build can never leak
into user evidence.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models import DocumentChunk, IndexVersion

logger = get_logger(__name__)


class EmbeddingProvider(Protocol):
    """The narrow embedding interface retrieval needs."""

    def embed_one(self, text: str) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Evidence contract shared by every product surface."""

    chunk_id: uuid.UUID
    index_version_id: uuid.UUID
    similarity: float
    text: str
    metadata: dict[str, Any]
    images: list[dict[str, Any]]
    source_url: str
    heading_anchor: str | None
    source_commit: str

    @property
    def citation_url(self) -> str:
        if not self.heading_anchor:
            return self.source_url
        return f"{self.source_url}#{self.heading_anchor}"


@dataclass(frozen=True, slots=True)
class LexicalRetrievalResult:
    """A literal-match candidate; its rank is not cosine similarity."""

    chunk_id: uuid.UUID
    index_version_id: uuid.UUID
    lexical_score: float
    text: str
    metadata: dict[str, Any]
    images: list[dict[str, Any]]
    source_url: str
    heading_anchor: str | None
    source_commit: str

    @property
    def citation_url(self) -> str:
        if not self.heading_anchor:
            return self.source_url
        return f"{self.source_url}#{self.heading_anchor}"


@dataclass(frozen=True, slots=True)
class ActiveIndex:
    id: uuid.UUID
    source_commit: str


@dataclass(frozen=True, slots=True)
class FusedRetrievalResult:
    """RRF output with every contributing rank preserved."""

    chunk_id: uuid.UUID
    index_version_id: uuid.UUID
    fusion_score: float
    dense_rank: int | None
    lexical_rank: int | None
    similarity: float | None
    lexical_score: float | None
    text: str
    metadata: dict[str, Any]
    images: list[dict[str, Any]]
    source_url: str
    heading_anchor: str | None
    source_commit: str

    @property
    def citation_url(self) -> str:
        if not self.heading_anchor:
            return self.source_url
        return f"{self.source_url}#{self.heading_anchor}"


Executor = AsyncSession | AsyncConnection


def reciprocal_rank_fusion(
    dense_results: Sequence[RetrievalResult],
    lexical_results: Sequence[LexicalRetrievalResult],
    *,
    settings: Settings | None = None,
) -> list[FusedRetrievalResult]:
    """Fuse heterogeneous rankings without pretending their scores align."""
    settings = settings or get_settings()
    dense_by_id = {result.chunk_id: (rank, result) for rank, result in enumerate(dense_results, 1)}
    lexical_by_id = {
        result.chunk_id: (rank, result) for rank, result in enumerate(lexical_results, 1)
    }
    fused: list[FusedRetrievalResult] = []

    for chunk_id in dense_by_id.keys() | lexical_by_id.keys():
        dense_entry = dense_by_id.get(chunk_id)
        lexical_entry = lexical_by_id.get(chunk_id)
        dense_rank, dense = dense_entry if dense_entry is not None else (None, None)
        lexical_rank, lexical = lexical_entry if lexical_entry is not None else (None, None)
        evidence = dense or lexical
        assert evidence is not None  # the chunk id came from at least one mapping

        fusion_score = 0.0
        if dense_rank is not None:
            fusion_score += settings.rrf_dense_weight / (settings.rrf_k + dense_rank)
        if lexical_rank is not None:
            fusion_score += settings.rrf_lexical_weight / (settings.rrf_k + lexical_rank)

        fused.append(
            FusedRetrievalResult(
                chunk_id=chunk_id,
                index_version_id=evidence.index_version_id,
                fusion_score=fusion_score,
                dense_rank=dense_rank,
                lexical_rank=lexical_rank,
                similarity=dense.similarity if dense is not None else None,
                lexical_score=lexical.lexical_score if lexical is not None else None,
                text=evidence.text,
                metadata=evidence.metadata,
                images=evidence.images,
                source_url=evidence.source_url,
                heading_anchor=evidence.heading_anchor,
                source_commit=evidence.source_commit,
            )
        )

    return sorted(fused, key=lambda result: (-result.fusion_score, str(result.chunk_id)))


def _dense_statement(query_vector: list[float], top_k: int) -> Select[tuple[Any, ...]]:
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    similarity = (1 - distance).label("similarity")
    return (
        select(
            DocumentChunk.id,
            DocumentChunk.index_version_id,
            similarity,
            DocumentChunk.text,
            DocumentChunk.source_url,
            DocumentChunk.source_path,
            DocumentChunk.source_commit,
            DocumentChunk.heading_anchor,
            DocumentChunk.section_title,
            DocumentChunk.breadcrumbs,
            DocumentChunk.content_type,
            DocumentChunk.code_languages,
            DocumentChunk.service,
            DocumentChunk.runtime,
            DocumentChunk.framework,
            DocumentChunk.language,
            DocumentChunk.images,
            DocumentChunk.extra_metadata,
        )
        .join(IndexVersion, IndexVersion.id == DocumentChunk.index_version_id)
        .where(
            IndexVersion.is_active.is_(True),
            DocumentChunk.embedding.is_not(None),
        )
        .order_by(distance, DocumentChunk.id)
        .limit(top_k)
    )


async def _require_active_index(executor: Executor) -> ActiveIndex:
    row = (
        await executor.execute(
            select(IndexVersion.id, IndexVersion.source_commit).where(
                IndexVersion.is_active.is_(True)
            )
        )
    ).one_or_none()
    if row is None:
        raise RescueError(
            ErrorCode.NO_ACTIVE_INDEX,
            detail="dense retrieval requested while no index version is active",
        )
    return ActiveIndex(id=row.id, source_commit=row.source_commit)


async def dense_retrieve_by_vector(
    executor: Executor,
    query_vector: list[float],
    *,
    settings: Settings | None = None,
    top_k: int | None = None,
) -> list[RetrievalResult]:
    """Rank active-index chunks by cosine similarity.

    This lower-level entry point exists so hybrid retrieval can reuse a single
    query embedding for multiple retrieval strategies.
    """
    settings = settings or get_settings()
    limit = top_k if top_k is not None else settings.retrieval_top_k
    if limit <= 0:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="retrieval top_k must be positive")
    if len(query_vector) != settings.embedding_dimensions:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail=(
                f"query embedding has {len(query_vector)} dimensions; "
                f"active schema expects {settings.embedding_dimensions}"
            ),
        )

    started = time.perf_counter()
    try:
        active = await _require_active_index(executor)
        rows = (await executor.execute(_dense_statement(query_vector, limit))).all()
    except RescueError:
        raise
    except SQLAlchemyError as err:
        raise RescueError(
            ErrorCode.RETRIEVAL_FAILED,
            detail="Postgres failed while executing dense retrieval",
        ) from err

    results = [
        RetrievalResult(
            chunk_id=row.id,
            index_version_id=row.index_version_id,
            similarity=float(row.similarity),
            text=row.text,
            metadata={
                "source_path": row.source_path,
                "section_title": row.section_title,
                "breadcrumbs": list(row.breadcrumbs or []),
                "content_type": row.content_type,
                "code_languages": list(row.code_languages or []),
                "service": row.service,
                "runtime": row.runtime,
                "framework": row.framework,
                "language": row.language,
                **dict(row.extra_metadata or {}),
            },
            images=list(row.images or []),
            source_url=row.source_url,
            heading_anchor=row.heading_anchor,
            source_commit=row.source_commit,
        )
        for row in rows
    ]
    logger.info(
        "dense retrieval completed",
        extra={
            "method": "dense",
            "index_version": str(active.id),
            "source_commit": active.source_commit,
            "result_count": len(results),
            "top_similarity": results[0].similarity if results else None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return results


async def dense_retrieve(
    executor: Executor,
    query: str,
    embeddings: EmbeddingProvider,
    *,
    settings: Settings | None = None,
    top_k: int | None = None,
) -> list[RetrievalResult]:
    """Normalize and embed a question, then search the active index."""
    normalized = normalize_query(query)
    if not normalized:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="retrieval query is empty")
    query_vector = await asyncio.to_thread(embeddings.embed_one, normalized)
    return await dense_retrieve_by_vector(
        executor,
        query_vector,
        settings=settings,
        top_k=top_k,
    )


async def lexical_retrieve(
    executor: Executor,
    query: str,
    *,
    settings: Settings | None = None,
    top_k: int | None = None,
) -> list[LexicalRetrievalResult]:
    """Find exact terms in normalized text through the generated tsvector."""
    settings = settings or get_settings()
    limit = top_k if top_k is not None else settings.retrieval_top_k
    if limit <= 0:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="retrieval top_k must be positive")
    normalized = normalize_query(query)
    if not normalized:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="retrieval query is empty")

    tsquery = func.websearch_to_tsquery("simple", normalized)
    lexical_score = func.ts_rank_cd(DocumentChunk.search_vector, tsquery).label("lexical_score")
    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.index_version_id,
            lexical_score,
            DocumentChunk.text,
            DocumentChunk.source_url,
            DocumentChunk.source_path,
            DocumentChunk.source_commit,
            DocumentChunk.heading_anchor,
            DocumentChunk.section_title,
            DocumentChunk.breadcrumbs,
            DocumentChunk.content_type,
            DocumentChunk.code_languages,
            DocumentChunk.service,
            DocumentChunk.runtime,
            DocumentChunk.framework,
            DocumentChunk.language,
            DocumentChunk.images,
            DocumentChunk.extra_metadata,
        )
        .join(IndexVersion, IndexVersion.id == DocumentChunk.index_version_id)
        .where(
            IndexVersion.is_active.is_(True),
            DocumentChunk.search_vector.op("@@")(tsquery),
        )
        .order_by(lexical_score.desc(), DocumentChunk.id)
        .limit(limit)
    )

    started = time.perf_counter()
    try:
        active = await _require_active_index(executor)
        rows = (await executor.execute(statement)).all()
    except RescueError:
        raise
    except SQLAlchemyError as err:
        raise RescueError(
            ErrorCode.RETRIEVAL_FAILED,
            detail="Postgres failed while executing lexical retrieval",
        ) from err

    results = [
        LexicalRetrievalResult(
            chunk_id=row.id,
            index_version_id=row.index_version_id,
            lexical_score=float(row.lexical_score),
            text=row.text,
            metadata={
                "source_path": row.source_path,
                "section_title": row.section_title,
                "breadcrumbs": list(row.breadcrumbs or []),
                "content_type": row.content_type,
                "code_languages": list(row.code_languages or []),
                "service": row.service,
                "runtime": row.runtime,
                "framework": row.framework,
                "language": row.language,
                **dict(row.extra_metadata or {}),
            },
            images=list(row.images or []),
            source_url=row.source_url,
            heading_anchor=row.heading_anchor,
            source_commit=row.source_commit,
        )
        for row in rows
    ]
    logger.info(
        "lexical retrieval completed",
        extra={
            "method": "lexical",
            "index_version": str(active.id),
            "source_commit": active.source_commit,
            "result_count": len(results),
            "top_lexical_score": results[0].lexical_score if results else None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return results


async def hybrid_retrieve(
    executor: Executor,
    query: str,
    embeddings: EmbeddingProvider,
    *,
    settings: Settings | None = None,
    top_k: int | None = None,
) -> list[FusedRetrievalResult]:
    """Run dense and lexical retrieval, then return their RRF ordering."""
    settings = settings or get_settings()
    limit = top_k if top_k is not None else settings.retrieval_top_k
    normalized = normalize_query(query)
    if not normalized:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="retrieval query is empty")

    query_vector = await asyncio.to_thread(embeddings.embed_one, normalized)
    dense = await dense_retrieve_by_vector(
        executor,
        query_vector,
        settings=settings,
        top_k=limit,
    )
    lexical = await lexical_retrieve(
        executor,
        normalized,
        settings=settings,
        top_k=limit,
    )
    fused = reciprocal_rank_fusion(dense, lexical, settings=settings)[:limit]
    logger.info(
        "hybrid retrieval fused",
        extra={
            "method": "rrf",
            "dense_count": len(dense),
            "lexical_count": len(lexical),
            "result_count": len(fused),
            "rrf_k": settings.rrf_k,
            "dense_weight": settings.rrf_dense_weight,
            "lexical_weight": settings.rrf_lexical_weight,
        },
    )
    return fused
