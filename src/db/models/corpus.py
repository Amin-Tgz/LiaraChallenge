"""The indexed documentation corpus: index versions, documents, chunks, images.

Index versioning is by row tagging, not table swapping — every document, chunk,
and image carries its `index_version_id`, and activation flips a single pointer
row. Retrieval always filters by the active version, so activation is atomic and
rollback is a second flip rather than a re-ingestion.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.config import get_settings
from src.core.normalization import NORMALIZER_VERSION
from src.db.models.base import Base, TimestampMixin
from src.db.models.enums import ChunkContentType, IndexStatus, enum_check

#: The stored vector width. Config-driven, but pinned at 1536 because pgvector
#: caps HNSW indexes at 2000 dimensions — see docs/deployment.md §2. Changing
#: EMBEDDING_DIMENSIONS is a schema change and autogenerates a migration.
EMBEDDING_DIM = get_settings().embedding_dimensions

JSONB_ = JSONB().with_variant(JSON(), "sqlite")
UUID_ = UUID(as_uuid=True)


class IndexVersion(Base, TimestampMixin):
    """One build of the corpus. Never mutated after activation."""

    __tablename__ = "index_versions"
    __table_args__ = (
        enum_check("status", IndexStatus, name="status"),
        # At most one active index. The partial unique index is what makes
        # activation a single-row update that cannot race into two active
        # versions; inactive rows carry NULL rather than false.
        Index(
            "uq_index_versions_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=IndexStatus.BUILDING)
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)

    # Provenance — what exactly was indexed.
    source_repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_branch: Mapped[str] = mapped_column(String(128), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    ingest_sections: Mapped[str] = mapped_column(String(512), nullable=False, default="*")

    # Reproducibility — a change to any of these invalidates the index.
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Stamped from the normalizer itself. An index built under a different
    #: version cannot be queried correctly by this one — it must be rebuilt.
    normalizer_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=NORMALIZER_VERSION
    )

    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Set when a build or its validation failed; a member of ErrorCode.
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_report: Mapped[dict | None] = mapped_column(JSONB_, nullable=True)

    documents: Mapped[list[Document]] = relationship(
        back_populates="index_version", cascade="all, delete-orphan"
    )


class Document(Base, TimestampMixin):
    """One source `.mdx` file as ingested into one index version."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("index_version_id", "source_path", name="uq_documents_index_source_path"),
        Index("ix_documents_index_version_id_content_hash", "index_version_id", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    index_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID_, ForeignKey("index_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str] = mapped_column(String(128), nullable=False)
    breadcrumbs: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)

    # Retrieval metadata, used for soft boosting.
    service: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="fa")

    #: Hash of the raw source, so an unchanged file is carried forward untouched.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: The pre-pass guardrail. A new upstream component shows up here as a
    #: metric change rather than as silent retrieval decay.
    discarded_char_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    flagged_for_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    index_version: Mapped[IndexVersion] = relationship(back_populates="documents")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base, TimestampMixin):
    """A retrievable unit of evidence, carrying everything a citation needs."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        enum_check("content_type", ChunkContentType, name="content_type"),
        UniqueConstraint("document_id", "ordinal", name="uq_document_chunks_document_id_ordinal"),
        # Lexical retrieval. Persian has no Postgres text-search configuration,
        # so `simple` over normalized text is what carries error strings,
        # commands, and service names — the cases that must match literally.
        Index("ix_document_chunks_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    index_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID_, ForeignKey("index_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID_, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    #: The same normalizer that runs on every query. Asymmetry here loses recall
    #: silently, which is why both paths call one function.
    text_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', text_normalized)", persisted=True),
        nullable=True,
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Citation identity: the document URL plus the section anchor, nothing inferred.
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    heading_anchor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    breadcrumbs: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)

    content_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ChunkContentType.PROSE
    )
    code_languages: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)
    service: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="fa")
    #: Images belonging to this chunk, denormalized so retrieval stays one query.
    images: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)
    extra_metadata: Mapped[dict] = mapped_column(JSONB_, nullable=False, default=dict)

    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class ImageAsset(Base, TimestampMixin):
    """An image and its alt text, resolvable independently of chunk denormalization."""

    __tablename__ = "image_assets"
    __table_args__ = (
        UniqueConstraint(
            "index_version_id", "document_id", "url", "ordinal", name="uq_image_assets_identity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    index_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID_, ForeignKey("index_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID_, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True, index=True
    )

    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    #: Alt text is also embedded with the surrounding prose, so a broken image
    #: URL leaves the answer intact.
    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    heading_anchor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
