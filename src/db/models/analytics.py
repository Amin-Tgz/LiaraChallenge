"""Recorded events — the only thing the dashboard is allowed to derive from.

Every figure on the operational dashboard traces to rows in this table. A metric
with no events must render an explicit no-data state, never a plausible number.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base, TimestampMixin
from src.db.models.enums import UsageEventType, enum_check

JSONB_ = JSONB().with_variant(JSON(), "sqlite")
UUID_ = UUID(as_uuid=True)


class UsageEvent(Base, TimestampMixin):
    """One observable thing that happened, with cost attributable to one request."""

    __tablename__ = "usage_events"
    __table_args__ = (
        enum_check("event_type", UsageEventType, name="event_type"),
        Index("ix_usage_events_event_type_created_at", "event_type", "created_at"),
        Index("ix_usage_events_error_code_created_at", "error_code", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Correlation identifiers, so one request is reconstructable from its events.
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("request_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    index_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("index_versions.id", ondelete="SET NULL"), nullable=True
    )
    faq_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("faq_items.id", ondelete="SET NULL"), nullable=True
    )

    #: Which rescue tool this event belongs to: skill, mcp, or chat.
    rescue_tool: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: A member of ErrorCode when the event records a failure or an abstention.
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: True when the gateway had to leave the primary provider.
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: USD. Verified unit price is $0.13 / 1M tokens — see docs/deployment.md §8.
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 8), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: The question this event concerns, for unresolved-gap aggregation.
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB_, nullable=False, default=dict)
