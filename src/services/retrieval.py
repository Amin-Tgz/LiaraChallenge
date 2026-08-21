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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from types import MappingProxyType
from typing import Any, Protocol

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models import Document, DocumentChunk, IndexVersion, UsageEvent
from src.db.models.enums import UsageEventType

logger = get_logger(__name__)

_METADATA_FIELDS = frozenset({"service", "runtime", "framework"})

#: Names callers use for a runtime, mapped to the token the corpus actually
#: stores. The index derives `runtime` from the documentation's own directory
#: names — `nodejs`, not `node` — so a caller saying the obvious thing filtered
#: every row away and got back "no relevant documentation found". A hard filter
#: is the one place in retrieval where being slightly wrong removes evidence
#: instead of reordering it, which is why these are worth normalizing rather
#: than leaving to the caller to guess.
_RUNTIME_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "node": "nodejs",
        "node.js": "nodejs",
        "nodejs": "nodejs",
        "js": "nodejs",
        "javascript": "nodejs",
        "typescript": "nodejs",
        "ts": "nodejs",
        "py": "python",
        "python3": "python",
        "golang": "go",
        ".net": "dotnet",
        "net": "dotnet",
        "csharp": "dotnet",
        "c#": "dotnet",
    }
)

_FIELD_ALIASES: Mapping[str, Mapping[str, str]] = MappingProxyType({"runtime": _RUNTIME_ALIASES})


def _canonical_filter_value(field_name: str, value: str) -> str:
    aliases = _FIELD_ALIASES.get(field_name)
    if aliases is None:
        return value
    return aliases.get(value, value)


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
class RetrievalIntent:
    """Profile hints are soft; only explicit filters may remove evidence."""

    profile_hints: Mapping[str, str] = field(default_factory=dict)
    explicit_filters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = (self.profile_hints.keys() | self.explicit_filters.keys()) - _METADATA_FIELDS
        if unknown:
            raise ValueError(f"unsupported retrieval metadata: {sorted(unknown)}")
        object.__setattr__(
            self,
            "profile_hints",
            {key: normalize_query(value) for key, value in self.profile_hints.items() if value},
        )
        object.__setattr__(
            self,
            "explicit_filters",
            {
                key: _canonical_filter_value(key, normalize_query(value))
                for key, value in self.explicit_filters.items()
                if value
            },
        )


@dataclass(frozen=True, slots=True)
class RetrievalTelemetry:
    trace_id: str | None = None
    session_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class FusedRetrievalResult:
    """RRF output with every contributing rank preserved."""

    chunk_id: uuid.UUID
    index_version_id: uuid.UUID
    fusion_score: float
    dense_rank: int | None
    lexical_rank: int | None
    similarity: float
    lexical_score: float | None
    text: str
    metadata: dict[str, Any]
    images: list[dict[str, Any]]
    source_url: str
    heading_anchor: str | None
    source_commit: str
    metadata_matches: tuple[str, ...] = ()
    boost_multiplier: float = 1.0

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
    lexical_similarities: Mapping[uuid.UUID, float] | None = None,
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
        if dense is not None:
            similarity = dense.similarity
        elif lexical_similarities is not None and chunk_id in lexical_similarities:
            similarity = lexical_similarities[chunk_id]
        else:
            raise ValueError("cosine similarity is required for every lexical-only fused candidate")

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
                similarity=similarity,
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


def apply_metadata_boosts(
    results: Sequence[FusedRetrievalResult],
    intent: RetrievalIntent,
    *,
    settings: Settings | None = None,
) -> list[FusedRetrievalResult]:
    """Softly reorder profile matches without removing any candidate."""
    settings = settings or get_settings()
    boosted: list[FusedRetrievalResult] = []
    for result in results:
        matches = tuple(
            key
            for key, expected in intent.profile_hints.items()
            if normalize_query(str(result.metadata.get(key) or "")) == expected
        )
        boosted.append(
            replace(
                result,
                metadata_matches=matches,
                boost_multiplier=1.0 + settings.retrieval_metadata_boost_weight * len(matches),
            )
        )
    return sorted(
        boosted,
        key=lambda result: (
            -(result.fusion_score * result.boost_multiplier),
            str(result.chunk_id),
        ),
    )


def _evidence_body(text: str) -> str:
    """Ignore the synthetic breadcrumb header when comparing evidence bodies."""
    _, separator, body = text.partition("\n\n")
    return normalize_query(body if separator else text)


def deduplicate_retrieval_results(
    results: Sequence[FusedRetrievalResult],
    *,
    threshold: float,
) -> list[FusedRetrievalResult]:
    """Keep ranking order while removing exact and near-identical passages."""
    accepted: list[FusedRetrievalResult] = []
    accepted_bodies: list[str] = []
    for result in results:
        body = _evidence_body(result.text)
        is_duplicate = any(
            body == prior
            or (
                body
                and prior
                and SequenceMatcher(None, body, prior, autojunk=False).ratio() >= threshold
            )
            for prior in accepted_bodies
        )
        if is_duplicate:
            continue
        accepted.append(result)
        accepted_bodies.append(body)
    return accepted


def _hard_filter_conditions(intent: RetrievalIntent | None) -> list[Any]:
    if intent is None:
        return []
    columns = {
        "service": DocumentChunk.service,
        "runtime": DocumentChunk.runtime,
        "framework": DocumentChunk.framework,
    }
    return [columns[key] == value for key, value in intent.explicit_filters.items()]


def _dense_statement(
    query_vector: list[float], top_k: int, intent: RetrievalIntent | None
) -> Select[tuple[Any, ...]]:
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
            Document.title.label("page_title"),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(IndexVersion, IndexVersion.id == DocumentChunk.index_version_id)
        .where(
            IndexVersion.is_active.is_(True),
            DocumentChunk.embedding.is_not(None),
            *_hard_filter_conditions(intent),
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
    intent: RetrievalIntent | None = None,
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
        rows = (await executor.execute(_dense_statement(query_vector, limit, intent))).all()
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
                "page_title": row.page_title,
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
    intent: RetrievalIntent | None = None,
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
        intent=intent,
    )


async def _similarities_for_chunks(
    executor: Executor,
    query_vector: list[float],
    chunk_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, float]:
    if not chunk_ids:
        return {}
    internal_distance = DocumentChunk.embedding.cosine_distance(query_vector)
    similarity = (1 - internal_distance).label("similarity")
    statement = (
        select(DocumentChunk.id, similarity)
        .join(IndexVersion, IndexVersion.id == DocumentChunk.index_version_id)
        .where(
            IndexVersion.is_active.is_(True),
            DocumentChunk.id.in_(chunk_ids),
            DocumentChunk.embedding.is_not(None),
        )
    )
    try:
        rows = (await executor.execute(statement)).all()
    except SQLAlchemyError as err:
        raise RescueError(
            ErrorCode.RETRIEVAL_FAILED,
            detail="Postgres failed while calculating candidate similarities",
        ) from err
    return {row.id: float(row.similarity) for row in rows}


async def lexical_retrieve(
    executor: Executor,
    query: str,
    *,
    settings: Settings | None = None,
    top_k: int | None = None,
    intent: RetrievalIntent | None = None,
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
            Document.title.label("page_title"),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(IndexVersion, IndexVersion.id == DocumentChunk.index_version_id)
        .where(
            IndexVersion.is_active.is_(True),
            DocumentChunk.search_vector.op("@@")(tsquery),
            *_hard_filter_conditions(intent),
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
                "page_title": row.page_title,
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
    intent: RetrievalIntent | None = None,
) -> list[FusedRetrievalResult]:
    """Run dense and lexical retrieval, then return their RRF ordering."""
    settings = settings or get_settings()
    limit = top_k if top_k is not None else settings.retrieval_top_k
    if limit <= 0:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="retrieval top_k must be positive")
    candidate_limit = limit * settings.retrieval_candidate_multiplier
    normalized = normalize_query(query)
    if not normalized:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail="retrieval query is empty")

    query_vector = await asyncio.to_thread(embeddings.embed_one, normalized)
    dense = await dense_retrieve_by_vector(
        executor,
        query_vector,
        settings=settings,
        top_k=candidate_limit,
        intent=intent,
    )
    lexical = await lexical_retrieve(
        executor,
        normalized,
        settings=settings,
        top_k=candidate_limit,
        intent=intent,
    )
    dense_ids = {result.chunk_id for result in dense}
    lexical_only_ids = [result.chunk_id for result in lexical if result.chunk_id not in dense_ids]
    lexical_similarities = await _similarities_for_chunks(
        executor,
        query_vector,
        lexical_only_ids,
    )
    fused = reciprocal_rank_fusion(
        dense,
        lexical,
        settings=settings,
        lexical_similarities=lexical_similarities,
    )
    if intent is not None and intent.profile_hints:
        fused = apply_metadata_boosts(fused, intent, settings=settings)
    fused = deduplicate_retrieval_results(
        fused,
        threshold=settings.retrieval_duplicate_threshold,
    )[:limit]
    logger.info(
        "hybrid retrieval fused",
        extra={
            "method": "rrf",
            "dense_count": len(dense),
            "lexical_count": len(lexical),
            "result_count": len(fused),
            "candidate_limit": candidate_limit,
            "top_similarity": fused[0].similarity if fused else None,
            "rrf_k": settings.rrf_k,
            "dense_weight": settings.rrf_dense_weight,
            "lexical_weight": settings.rrf_lexical_weight,
        },
    )
    return fused


async def _record_retrieval_event(
    executor: Executor,
    *,
    query: str,
    results: Sequence[FusedRetrievalResult],
    threshold: float,
    telemetry: RetrievalTelemetry,
    error_code: ErrorCode | None = None,
) -> None:
    """Best-effort telemetry; its failure never changes the user outcome."""
    active_id = results[0].index_version_id if results else None
    try:
        await executor.execute(
            UsageEvent.__table__.insert().values(
                event_type=UsageEventType.RETRIEVAL.value,
                trace_id=telemetry.trace_id,
                session_id=telemetry.session_id,
                conversation_id=telemetry.conversation_id,
                job_id=telemetry.job_id,
                index_version_id=active_id,
                error_code=error_code.value if error_code is not None else None,
                question=query,
                payload={
                    "similarity_threshold": threshold,
                    "candidate_count": len(results),
                    "top_similarity": results[0].similarity if results else None,
                },
            )
        )
    except SQLAlchemyError as err:
        logger.warning(
            "retrieval telemetry failed",
            extra={
                "error_code": error_code.value if error_code is not None else None,
                "trace_id": telemetry.trace_id,
                "cause": str(err),
            },
        )


async def _unmatched_filters(
    executor: Executor, intent: RetrievalIntent | None
) -> dict[str, list[str]]:
    """Explicit filter values the active index does not use, with what it does.

    Only consulted when a search comes back empty, so the common path pays
    nothing. It exists because a hard filter on a value the corpus never stores
    removes every candidate, and the resulting emptiness is indistinguishable
    from a genuine documentation gap — the exact conflation RULES.md §1 forbids.
    """
    if intent is None or not intent.explicit_filters:
        return {}

    columns = {
        "service": DocumentChunk.service,
        "runtime": DocumentChunk.runtime,
        "framework": DocumentChunk.framework,
    }
    unmatched: dict[str, list[str]] = {}
    for field_name, requested in intent.explicit_filters.items():
        column = columns[field_name]
        rows = await executor.execute(
            select(column)
            .join(IndexVersion, IndexVersion.id == DocumentChunk.index_version_id)
            .where(IndexVersion.is_active.is_(True), column.is_not(None))
            .distinct()
        )
        present = sorted({str(value) for (value,) in rows})
        if requested not in present:
            unmatched[field_name] = present
    return unmatched


async def search_documentation(
    executor: Executor,
    query: str,
    embeddings: EmbeddingProvider,
    *,
    settings: Settings | None = None,
    top_k: int | None = None,
    intent: RetrievalIntent | None = None,
    telemetry: RetrievalTelemetry | None = None,
) -> list[FusedRetrievalResult]:
    """Public retrieval contract with thresholding and distinct failures."""
    settings = settings or get_settings()
    telemetry = telemetry or RetrievalTelemetry()
    try:
        results = await hybrid_retrieve(
            executor,
            query,
            embeddings,
            settings=settings,
            top_k=top_k,
            intent=intent,
        )
    except RescueError as err:
        await _record_retrieval_event(
            executor,
            query=query,
            results=[],
            threshold=settings.retrieval_similarity_threshold,
            telemetry=telemetry,
            error_code=err.code,
        )
        logger.warning(
            "documentation retrieval failed",
            extra={
                "error_code": err.code.value,
                "trace_id": telemetry.trace_id,
                **err.context,
            },
        )
        raise

    above_threshold = [
        result for result in results if result.similarity >= settings.retrieval_similarity_threshold
    ]
    if not above_threshold:
        # Before calling this a documentation gap, rule out the caller having
        # filtered on a value the corpus does not use. Both look like "nothing
        # found"; only one of them is about the documentation.
        unmatched = await _unmatched_filters(executor, intent)
        if unmatched:
            field_name, present = next(iter(unmatched.items()))
            requested = intent.explicit_filters[field_name] if intent else ""
            filter_code = ErrorCode.NO_RESULTS_FOR_FILTER
            await _record_retrieval_event(
                executor,
                query=query,
                results=results,
                threshold=settings.retrieval_similarity_threshold,
                telemetry=telemetry,
                error_code=filter_code,
            )
            logger.info(
                "retrieval filtered on a value the corpus does not use",
                extra={
                    "error_code": filter_code.value,
                    "trace_id": telemetry.trace_id,
                    "filter_field": field_name,
                    "filter_value": requested,
                },
            )
            raise RescueError(
                filter_code,
                detail=(
                    f"{field_name}={requested!r} matches no chunk in the active index; "
                    f"values present: {', '.join(present) or '(none)'}"
                ),
                context={
                    "filter_field": field_name,
                    "filter_value": requested,
                    "filter_values_present": present,
                },
            )
        code = ErrorCode.NO_RESULTS_ABOVE_THRESHOLD
        await _record_retrieval_event(
            executor,
            query=query,
            results=results,
            threshold=settings.retrieval_similarity_threshold,
            telemetry=telemetry,
            error_code=code,
        )
        logger.info(
            "no documentation results above similarity threshold",
            extra={
                "error_code": code.value,
                "trace_id": telemetry.trace_id,
                "similarity_threshold": settings.retrieval_similarity_threshold,
                "top_similarity": results[0].similarity if results else None,
            },
        )
        raise RescueError(
            code,
            detail=(
                "active index searched successfully; no candidate reached "
                f"similarity {settings.retrieval_similarity_threshold}"
            ),
            context={
                "trace_id": telemetry.trace_id,
                "index_version": str(results[0].index_version_id) if results else None,
            },
        )

    await _record_retrieval_event(
        executor,
        query=query,
        results=above_threshold,
        threshold=settings.retrieval_similarity_threshold,
        telemetry=telemetry,
    )
    return above_threshold
