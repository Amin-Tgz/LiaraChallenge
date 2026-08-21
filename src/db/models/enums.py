"""Enumerations shared by models, services, and API responses.

Stored as text with a CHECK constraint rather than a native Postgres enum:
adding a state stays a one-line migration instead of an `ALTER TYPE` that
cannot run inside a transaction on older servers.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class JobStatus(StrEnum):
    """The job state machine from the chat-agent spec.

    queued → retrieving → generating → completed
                       ↘ retrying ↗
                       ↘ failed (terminal)
    """

    QUEUED = "queued"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset({JobStatus.COMPLETED, JobStatus.FAILED})


class FeedbackOutcome(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class FeedbackStage(StrEnum):
    """Where in the rescue flow the feedback was given."""

    FAQ = "faq"
    CHAT = "chat"


class FeedbackReason(StrEnum):
    """Why an answer fell short.

    A thumbs-down that says only "bad" cannot be acted on. These four separate
    the failures that need different fixes: a wrong claim is a grounding
    problem, a thin answer is a corpus problem, an off-topic answer is a
    retrieval problem, and a bad source is a chunking or citation problem.
    """

    INCORRECT = "incorrect"
    INCOMPLETE = "incomplete"
    IRRELEVANT = "irrelevant"
    WRONG_SOURCE = "wrong_source"
    OTHER = "other"


class RescueTool(StrEnum):
    SKILL = "skill"
    MCP = "mcp"
    CHAT = "chat"


class FaqStatus(StrEnum):
    """Curated entries must be distinguishable from unreviewed ones."""

    GENERATED = "generated"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class IndexStatus(StrEnum):
    """An index is never mutated in place; it moves through these states."""

    BUILDING = "building"
    VALIDATING = "validating"
    READY = "ready"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class ChunkContentType(StrEnum):
    PROSE = "prose"
    CODE = "code"
    STEP = "step"
    TABLE = "table"
    MIXED = "mixed"


class UsageEventType(StrEnum):
    """Every dashboard figure derives from one of these recorded events."""

    FAQ_IMPRESSION = "faq_impression"
    FAQ_SELECTION = "faq_selection"
    FAQ_RESOLUTION = "faq_resolution"
    CHAT_RESOLUTION = "chat_resolution"
    RESCUE_TOOL_TRANSITION = "rescue_tool_transition"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"
    PROVIDER_FALLBACK = "provider_fallback"
    JOB_OUTCOME = "job_outcome"
    ERROR = "error"
    INGESTION = "ingestion"


def enum_check(column: str, enum: type[StrEnum], *, name: str) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({values})", name=name)
