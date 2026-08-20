"""Building, validating, activating, and rolling back an index version.

The active index is never mutated. Every run builds a new version, proves it is
usable, and then flips one pointer row. That ordering is what makes a failed
ingestion a non-event for users: the previous index keeps serving, and the
failure is recorded with a code that names which stage failed.

Three costs are avoided deliberately:

* an unchanged upstream commit exits before a single embedding is generated;
* an unchanged *document* is carried forward with its existing vectors rather
  than re-embedded;
* documents are streamed one at a time — the worker has 1 GB and the corpus is
  over a thousand files.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.normalization import NORMALIZER_VERSION
from src.db.models import Document, DocumentChunk, ImageAsset, IndexVersion, UsageEvent
from src.db.models.enums import IndexStatus, UsageEventType
from src.services.embeddings import EmbeddingClient
from src.services.ingestion.chunking import Chunk, chunk_document
from src.services.ingestion.mdx import transform_mdx
from src.services.ingestion.repository import (
    Checkout,
    SourceDocument,
    discover_documents,
    fetch_corpus,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class DocumentReport:
    """What happened to one document, including the pre-pass guardrail metric."""

    source_path: str
    outcome: str  # added | modified | carried_forward | empty
    chunk_count: int = 0
    discarded_char_ratio: float = 0.0
    flagged_for_review: bool = False
    unrecognized_tags: tuple[str, ...] = ()
    embedding_tokens: int = 0
    error_code: str | None = None


@dataclass(slots=True)
class IngestionReport:
    """The outcome of one run, in the terms an operator needs.

    `no_change` is a first-class outcome, not a degenerate success: it is what
    the scheduled reindex reports on the overwhelming majority of its runs.
    """

    status: str  # no_change | activated | validation_failed | failed
    source_commit: str
    index_version_id: uuid.UUID | None = None
    documents_total: int = 0
    added: int = 0
    modified: int = 0
    carried_forward: int = 0
    deleted: int = 0
    chunks_total: int = 0
    embeddings_generated: int = 0
    embedding_tokens: int = 0
    flagged_documents: list[str] = field(default_factory=list)
    documents: list[DocumentReport] = field(default_factory=list)
    error_code: str | None = None
    detail: str | None = None
    validation_report: dict[str, Any] = field(default_factory=dict)

    @property
    def embeddings_skipped(self) -> bool:
        return self.embeddings_generated == 0

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_commit": self.source_commit,
            "index_version_id": str(self.index_version_id) if self.index_version_id else None,
            "documents_total": self.documents_total,
            "added": self.added,
            "modified": self.modified,
            "carried_forward": self.carried_forward,
            "deleted": self.deleted,
            "chunks_total": self.chunks_total,
            "embeddings_generated": self.embeddings_generated,
            "embedding_tokens": self.embedding_tokens,
            "flagged_documents": len(self.flagged_documents),
            "error_code": self.error_code,
        }


async def active_index_version(session: AsyncSession) -> IndexVersion | None:
    result = await session.execute(select(IndexVersion).where(IndexVersion.is_active.is_(True)))
    return result.scalar_one_or_none()


async def _existing_hashes(session: AsyncSession, index_version_id: uuid.UUID) -> dict[str, str]:
    rows = await session.execute(
        select(Document.source_path, Document.content_hash).where(
            Document.index_version_id == index_version_id
        )
    )
    return dict(rows.all())


#: Chunks are written as Core inserts rather than ORM objects on purpose. The
#: corpus produces thousands of 1536-float vectors, and an ORM identity map
#: holding all of them is how a 1 GB worker runs out of memory two thirds of the
#: way through an ingestion.
def _chunk_values(
    chunk: Chunk,
    *,
    index_version_id: uuid.UUID,
    document_id: uuid.UUID,
    source_commit: str,
    embedding_model: str,
    embedding_dimensions: int,
    embedding: list[float] | None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "index_version_id": index_version_id,
        "document_id": document_id,
        "ordinal": chunk.ordinal,
        "text": chunk.text,
        "text_normalized": chunk.text_normalized,
        "token_count": chunk.token_count,
        "source_url": chunk.source_url,
        "source_path": chunk.source_path,
        "source_commit": source_commit,
        "heading_anchor": chunk.heading_anchor,
        "section_title": chunk.section_title,
        "breadcrumbs": chunk.breadcrumbs,
        "content_type": chunk.content_type,
        "code_languages": chunk.code_languages,
        "service": chunk.service,
        "runtime": chunk.runtime,
        "framework": chunk.framework,
        "language": chunk.language,
        "images": chunk.images,
        "extra_metadata": chunk.extra_metadata,
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions,
        "embedding": embedding,
    }


async def _ingest_document(
    session: AsyncSession,
    source: SourceDocument,
    *,
    index_version: IndexVersion,
    checkout: Checkout,
    embeddings: EmbeddingClient,
    settings: Settings,
    outcome: str,
) -> DocumentReport:
    """Parse, chunk, embed, and store one document."""
    parsed = transform_mdx(source.text)
    chunks = chunk_document(parsed, source_path=source.source_path, settings=settings)
    if not chunks:
        # A page that legitimately holds no indexable prose. Distinct from
        # DOCUMENT_PARSE_FAILED, which chunk_document raises when a document
        # that *does* have text yields nothing.
        return DocumentReport(
            source_path=source.source_path,
            outcome="empty",
            discarded_char_ratio=parsed.discarded_char_ratio,
            flagged_for_review=parsed.flagged_for_review,
            unrecognized_tags=parsed.unrecognized_tags,
        )

    document = Document(
        id=uuid.uuid4(),
        index_version_id=index_version.id,
        source_path=source.source_path,
        source_url=chunks[0].source_url,
        source_commit=checkout.commit,
        title=parsed.title or source.source_path,
        section=source.section,
        breadcrumbs=chunks[0].breadcrumbs,
        service=chunks[0].service,
        runtime=chunks[0].runtime,
        framework=chunks[0].framework,
        language=chunks[0].language,
        content_hash=source.content_hash,
        source_char_count=source.char_count,
        discarded_char_ratio=parsed.discarded_char_ratio,
        flagged_for_review=parsed.flagged_for_review,
    )
    session.add(document)

    # Embeddings are generated over the *normalized* text, the same form the
    # query side produces. Embedding raw text here and normalized text there
    # would be the same silent asymmetry the normalizer exists to prevent.
    batch = embeddings.embed([chunk.text_normalized for chunk in chunks])
    await session.execute(
        insert(DocumentChunk),
        [
            _chunk_values(
                chunk,
                index_version_id=index_version.id,
                document_id=document.id,
                source_commit=checkout.commit,
                embedding_model=embeddings.model,
                embedding_dimensions=embeddings.dimensions,
                embedding=vector,
            )
            for chunk, vector in zip(chunks, batch.vectors, strict=True)
        ],
    )

    if parsed.images:
        await session.execute(
            insert(ImageAsset),
            [
                {
                    "id": uuid.uuid4(),
                    "index_version_id": index_version.id,
                    "document_id": document.id,
                    "url": image.url,
                    "alt_text": image.alt,
                    "heading_anchor": image.heading_anchor,
                    "ordinal": image.ordinal,
                }
                for image in parsed.images
            ],
        )

    return DocumentReport(
        source_path=source.source_path,
        outcome=outcome,
        chunk_count=len(chunks),
        discarded_char_ratio=parsed.discarded_char_ratio,
        flagged_for_review=parsed.flagged_for_review,
        unrecognized_tags=parsed.unrecognized_tags,
        embedding_tokens=batch.total_tokens,
    )


async def _carry_forward(
    session: AsyncSession,
    source_path: str,
    *,
    from_index_version_id: uuid.UUID,
    index_version: IndexVersion,
) -> DocumentReport:
    """Copy an unchanged document and its vectors into the new version.

    This is the whole point of change detection: an unchanged document costs a
    row copy instead of an embedding call.
    """
    previous = (
        await session.execute(
            select(Document).where(
                Document.index_version_id == from_index_version_id,
                Document.source_path == source_path,
            )
        )
    ).scalar_one()

    document = Document(
        id=uuid.uuid4(),
        index_version_id=index_version.id,
        source_path=previous.source_path,
        source_url=previous.source_url,
        source_commit=previous.source_commit,
        title=previous.title,
        section=previous.section,
        breadcrumbs=previous.breadcrumbs,
        service=previous.service,
        runtime=previous.runtime,
        framework=previous.framework,
        language=previous.language,
        content_hash=previous.content_hash,
        source_char_count=previous.source_char_count,
        discarded_char_ratio=previous.discarded_char_ratio,
        flagged_for_review=previous.flagged_for_review,
    )
    session.add(document)

    # Copied column-wise in the database's own terms: the vectors never need to
    # become Python lists just to be written back unchanged.
    carried = [
        {
            **{
                column.name: getattr(row, column.name)
                for column in DocumentChunk.__table__.columns
                if column.name not in {"id", "index_version_id", "document_id", "search_vector"}
                and not column.computed
            },
            "id": uuid.uuid4(),
            "index_version_id": index_version.id,
            "document_id": document.id,
        }
        for row in (
            await session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == previous.id)
            )
        ).scalars()
    ]
    if carried:
        await session.execute(insert(DocumentChunk), carried)

    images = [
        {
            "id": uuid.uuid4(),
            "index_version_id": index_version.id,
            "document_id": document.id,
            "url": row.url,
            "alt_text": row.alt_text,
            "caption": row.caption,
            "heading_anchor": row.heading_anchor,
            "ordinal": row.ordinal,
        }
        for row in (
            await session.execute(select(ImageAsset).where(ImageAsset.document_id == previous.id))
        ).scalars()
    ]
    if images:
        await session.execute(insert(ImageAsset), images)
    count = len(carried)

    return DocumentReport(
        source_path=source_path,
        outcome="carried_forward",
        chunk_count=count,
        discarded_char_ratio=previous.discarded_char_ratio,
        flagged_for_review=previous.flagged_for_review,
    )


async def validate_index(
    session: AsyncSession, index_version: IndexVersion, settings: Settings
) -> dict[str, Any]:
    """Smoke-check a freshly built index before anything depends on it.

    Every check here corresponds to a way an index can be structurally present
    and functionally useless — the state that otherwise reaches users as a
    confident empty answer.
    """
    checks: dict[str, Any] = {}

    chunk_count = (
        await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.index_version_id == index_version.id)
        )
    ).scalar_one()
    checks["chunk_count"] = {"ok": chunk_count > 0, "value": chunk_count}

    document_count = (
        await session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.index_version_id == index_version.id)
        )
    ).scalar_one()
    checks["document_count"] = {"ok": document_count > 0, "value": document_count}

    missing_embeddings = (
        await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.index_version_id == index_version.id,
                DocumentChunk.embedding.is_(None),
            )
        )
    ).scalar_one()
    checks["embeddings_present"] = {"ok": missing_embeddings == 0, "missing": missing_embeddings}

    wrong_dimensions = (
        await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.index_version_id == index_version.id,
                DocumentChunk.embedding_dimensions != settings.embedding_dimensions,
            )
        )
    ).scalar_one()
    checks["dimensions_consistent"] = {
        "ok": wrong_dimensions == 0,
        "expected": settings.embedding_dimensions,
        "mismatched": wrong_dimensions,
    }

    out_of_bounds = (
        await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.index_version_id == index_version.id,
                (DocumentChunk.token_count > settings.chunk_max_tokens),
            )
        )
    ).scalar_one()
    checks["chunk_sizes"] = {"ok": out_of_bounds == 0, "over_maximum": out_of_bounds}

    # A citation that cannot deep-link is a citation a user cannot verify.
    uncitable = (
        await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.index_version_id == index_version.id,
                (DocumentChunk.source_url == "") | (DocumentChunk.source_commit == ""),
            )
        )
    ).scalar_one()
    checks["citations_resolvable"] = {"ok": uncitable == 0, "uncitable": uncitable}

    checks["passed"] = all(
        check["ok"] for check in checks.values() if isinstance(check, dict) and "ok" in check
    )
    return checks


async def activate(session: AsyncSession, index_version: IndexVersion) -> None:
    """Flip the active pointer in one statement pair, inside one transaction.

    Retrieval filters on the active version, so a reader sees entirely the old
    index or entirely the new one — never a mixture.
    """
    await session.execute(
        update(IndexVersion)
        .where(IndexVersion.is_active.is_(True))
        .values(is_active=None, status=IndexStatus.SUPERSEDED.value)
    )
    await session.execute(
        update(IndexVersion)
        .where(IndexVersion.id == index_version.id)
        .values(
            is_active=True,
            status=IndexStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
        )
    )


async def prune_old_versions(session: AsyncSession, settings: Settings) -> int:
    """Drop versions beyond the retention window.

    Never touches the active version, and always leaves at least one superseded
    version behind — retention is what makes rollback possible at all.
    """
    keep = max(settings.index_retention_count, 1)
    superseded = (
        (
            await session.execute(
                select(IndexVersion.id)
                .where(IndexVersion.is_active.is_(None))
                .order_by(IndexVersion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    doomed = list(superseded[keep:])
    if not doomed:
        return 0
    await session.execute(delete(IndexVersion).where(IndexVersion.id.in_(doomed)))
    return len(doomed)


async def rollback_to(session: AsyncSession, index_version_id: uuid.UUID) -> IndexVersion:
    """Reactivate a prior version without re-running ingestion.

    Rollback is a pointer flip precisely because chunks are tagged with their
    version rather than swapped between tables — the old vectors never left.
    """
    target = (
        await session.execute(select(IndexVersion).where(IndexVersion.id == index_version_id))
    ).scalar_one_or_none()
    if target is None:
        raise RescueError(
            ErrorCode.NO_ACTIVE_INDEX,
            detail=f"index version {index_version_id} does not exist",
        )
    chunk_count = (
        await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.index_version_id == target.id)
        )
    ).scalar_one()
    if chunk_count == 0:
        # Rolling back onto an empty index would trade a suspected fault for a
        # certain outage.
        raise RescueError(
            ErrorCode.INDEX_VALIDATION_FAILED,
            detail=f"index version {index_version_id} holds no chunks; refusing to activate",
        )

    await activate(session, target)
    await session.commit()
    logger.info(
        "index rolled back",
        extra={"index_version": str(target.id), "source_commit": target.source_commit},
    )
    return target


async def run_ingestion(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings | None = None,
    embeddings: EmbeddingClient | None = None,
    force: bool = False,
) -> IngestionReport:
    """Build and activate a new index version from the configured corpus."""
    settings = settings or get_settings()
    checkout = fetch_corpus(settings)

    async with session_factory() as session:
        current = await active_index_version(session)

        if current is not None and current.source_commit == checkout.commit and not force:
            # The expensive path is not merely skipped — it is never entered.
            # A scheduled reindex hits this branch on almost every run.
            logger.info(
                "upstream unchanged; no embeddings generated",
                extra={"commit": checkout.commit, "index_version": str(current.id)},
            )
            return IngestionReport(
                status="no_change",
                source_commit=checkout.commit,
                index_version_id=current.id,
                documents_total=current.document_count,
                chunks_total=current.chunk_count,
            )

        sources = discover_documents(checkout, settings)
        previous_hashes = await _existing_hashes(session, current.id) if current else {}
        report = IngestionReport(
            status="failed",
            source_commit=checkout.commit,
            documents_total=len(sources),
            deleted=len(set(previous_hashes) - {s.source_path for s in sources}),
        )

        index_version = IndexVersion(
            id=uuid.uuid4(),
            status=IndexStatus.BUILDING.value,
            is_active=None,
            source_repo_url=checkout.repo_url,
            source_branch=checkout.branch,
            source_commit=checkout.commit,
            ingest_sections=settings.ingest_sections,
            embedding_model=settings.embedding_model,
            embedding_dimensions=settings.embedding_dimensions,
            normalizer_version=NORMALIZER_VERSION,
        )
        session.add(index_version)
        await session.flush()
        report.index_version_id = index_version.id

        owns_embeddings = embeddings is None
        embeddings = embeddings or EmbeddingClient(settings)
        try:
            for source in sources:
                previous_hash = previous_hashes.get(source.source_path)
                if current is not None and previous_hash == source.content_hash:
                    document_report = await _carry_forward(
                        session,
                        source.source_path,
                        from_index_version_id=current.id,
                        index_version=index_version,
                    )
                    report.carried_forward += 1
                else:
                    outcome = "modified" if previous_hash else "added"
                    document_report = await _ingest_document(
                        session,
                        source,
                        index_version=index_version,
                        checkout=checkout,
                        embeddings=embeddings,
                        settings=settings,
                        outcome=outcome,
                    )
                    report.embeddings_generated += document_report.chunk_count
                    if outcome == "modified":
                        report.modified += 1
                    else:
                        report.added += 1

                report.chunks_total += document_report.chunk_count
                report.embedding_tokens += document_report.embedding_tokens
                if document_report.flagged_for_review:
                    report.flagged_documents.append(document_report.source_path)
                report.documents.append(document_report)
                # One document at a time reaches the database, so the corpus is
                # never resident in memory all at once.
                await session.flush()

            index_version.document_count = len(sources)
            index_version.chunk_count = report.chunks_total
            index_version.status = IndexStatus.VALIDATING.value
            await session.flush()

            validation = await validate_index(session, index_version, settings)
            report.validation_report = validation
            index_version.validation_report = validation

            if not validation["passed"]:
                # The prior index is untouched by construction: nothing above
                # this line modified it.
                index_version.status = IndexStatus.FAILED.value
                index_version.error_code = ErrorCode.INDEX_VALIDATION_FAILED.value
                await session.commit()
                report.status = "validation_failed"
                report.error_code = ErrorCode.INDEX_VALIDATION_FAILED.value
                report.detail = "; ".join(
                    name
                    for name, check in validation.items()
                    if isinstance(check, dict) and not check.get("ok", True)
                )
                logger.error(
                    "index validation failed; previous index still active",
                    extra={
                        "index_version": str(index_version.id),
                        "error_code": report.error_code,
                        "failed_checks": report.detail,
                    },
                )
                return report

            await activate(session, index_version)
            pruned = await prune_old_versions(session, settings)
            session.add(
                UsageEvent(
                    id=uuid.uuid4(),
                    event_type=UsageEventType.INGESTION.value,
                    index_version_id=index_version.id,
                    model=settings.embedding_model,
                    total_tokens=report.embedding_tokens,
                    payload={
                        **report.summary(),
                        "pruned_versions": pruned,
                        "normalizer_version": NORMALIZER_VERSION,
                    },
                )
            )
            await session.commit()
        except RescueError as err:
            await session.rollback()
            report.status = "failed"
            report.error_code = err.code.value
            report.detail = err.detail
            logger.error(
                "ingestion failed; previous index still active",
                extra={"error_code": err.code.value, "detail": err.detail},
            )
            return report
        finally:
            if owns_embeddings:
                embeddings.close()

        report.status = "activated"
        logger.info("index activated", extra=report.summary())
        return report
