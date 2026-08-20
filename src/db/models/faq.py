"""Documentation-derived question/answer pairs — the fast path.

FAQ questions live in their own embedding space: matching compares a question
against *questions*, not against passages, which is better behaved and keeps the
fast path independent of chunking changes.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base, TimestampMixin
from src.db.models.corpus import EMBEDDING_DIM
from src.db.models.enums import FaqStatus, enum_check

JSONB_ = JSONB().with_variant(JSON(), "sqlite")
UUID_ = UUID(as_uuid=True)


class FaqItem(Base, TimestampMixin):
    """One generated or curated pair, always attributable to its source section."""

    __tablename__ = "faq_items"
    __table_args__ = (
        enum_check("status", FaqStatus, name="status"),
        Index("ix_faq_items_status_is_active", "status", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    #: Normalized by the same function used at query time — asymmetry here
    #: silently loses matches.
    question_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    # Provenance. An entry that cannot name its source is not shippable.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    heading_anchor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Hash of the source document at generation time, so incremental runs skip
    #: unchanged documents and leave their entries intact.
    source_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=FaqStatus.GENERATED)
    #: False hides an entry from user-facing results without losing its history.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Curated ordering weight, combined with similarity at match time.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tags: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)

    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Null means the question changed and awaits re-embedding; such an entry
    #: cannot match until it is embedded again.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
