"""Anonymous sessions, conversations, messages, jobs, and resolution feedback.

The question is persisted before anything else happens, and the job that answers
it is persisted before it is enqueued — reload, disconnect, and worker restart
are ordinary events here, not exceptional ones.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base, TimestampMixin
from src.db.models.enums import (
    FeedbackOutcome,
    FeedbackReason,
    FeedbackStage,
    JobStatus,
    MessageRole,
    enum_check,
)

JSONB_ = JSONB().with_variant(JSON(), "sqlite")
UUID_ = UUID(as_uuid=True)


class AnonymousSession(Base, TimestampMixin):
    """A cookie-scoped visitor. No account, no login, no personal profile."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: Hashed, never the raw address — used only for rate limiting and abuse.
    client_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    conversations: Mapped[list[Conversation]] = relationship(back_populates="session")


class Conversation(Base, TimestampMixin):
    """One rescue attempt, from the landing question through to an answer."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID_, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Captured once on the landing view and never retyped by the user.
    initial_question: Mapped[str] = mapped_column(Text, nullable=False)
    initial_question_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Service, runtime, framework, experience, goal, deployment mode, known
    #: error. Schema-free JSON because it is read whole every turn and its
    #: fields evolve faster than migrations would.
    technical_profile: Mapped[dict] = mapped_column(JSONB_, nullable=False, default=dict)
    #: Which rescue tool the user moved to, if any.
    rescue_tool: Mapped[str | None] = mapped_column(String(16), nullable=True)

    #: A running Persian summary of the turns that have fallen out of the
    #: verbatim history window. This is what lets a conversation continue past
    #: the old three-turn cutoff without the token cost growing with its length.
    history_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The highest message ordinal already folded into `history_summary`. Older
    #: turns are summarized once and never re-read, so each turn costs at most
    #: one summarization call.
    history_summarized_through_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[AnonymousSession] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[RequestJob]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base, TimestampMixin):
    """One turn. Assistant turns carry the citations that justify them."""

    __tablename__ = "messages"
    __table_args__ = (
        enum_check("role", MessageRole, name="role"),
        UniqueConstraint("conversation_id", "ordinal", name="uq_messages_conversation_id_ordinal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID_, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: Every technical claim traces to one of these. An assistant message with
    #: no citations is either an abstention or a bug.
    citations: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)
    images: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)
    #: Set when the turn ended in a named failure or abstention.
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Name of the tool for tool-role messages.
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    index_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("index_versions.id", ondelete="SET NULL"), nullable=True
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class RequestJob(Base, TimestampMixin):
    """A unit of answering work, persisted before it is enqueued."""

    __tablename__ = "request_jobs"
    __table_args__ = (
        enum_check("status", JobStatus, name="status"),
        # Idempotency is what makes reload-during-generation safe: a resubmitted
        # key returns the existing job instead of creating a second one.
        UniqueConstraint("idempotency_key", name="uq_request_jobs_idempotency_key"),
        Index("ix_request_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID_, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.QUEUED)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    #: Append-only record of every state change, so a job's history is
    #: reconstructable without log archaeology.
    transitions: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)

    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    #: A member of ErrorCode. Never a free-text failure message.
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Redis Stream the worker appends tokens to and the SSE endpoint tails.
    stream_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Offset of the last token handed to a client, so reconnection resumes
    #: rather than restarts.
    last_delivered_offset: Mapped[str | None] = mapped_column(String(64), nullable=True)

    result_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="jobs")


class Feedback(Base, TimestampMixin):
    """Whether the user actually got their answer.

    An unresolved outcome is the product's most valuable analytics signal — it
    names a real documentation gap — so it is stored with the question and the
    entries that were shown, not merely counted.
    """

    __tablename__ = "feedback"
    __table_args__ = (
        enum_check("outcome", FeedbackOutcome, name="outcome"),
        enum_check("stage", FeedbackStage, name="stage"),
        CheckConstraint(
            "reason IS NULL OR reason IN ("
            + ", ".join(f"'{member.value}'" for member in FeedbackReason)
            + ")",
            name="reason",
        ),
        # The admin console reads chat feedback for a time window on every load.
        Index("ix_feedback_stage_created_at", "stage", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )

    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    #: The FAQ entries that were on screen when the user judged the result.
    presented_faq_ids: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)
    #: The documentation pages implicated, so unresolved feedback aggregates by page.
    source_urls: Mapped[list] = mapped_column(JSONB_, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: The assistant answer being judged, for chat-stage feedback. FAQ-stage
    #: feedback judges a set of offered entries rather than one message, so this
    #: stays null there.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Why the answer fell short, from a fixed set. Free text lives in `note`;
    #: this is the part that aggregates.
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
