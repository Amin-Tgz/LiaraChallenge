"""conversation history summary and chat-stage answer feedback

Revision ID: c7f1d2b40e51
Revises: 9a26e36a7b99
Create Date: 2026-08-21 19:30:00.000000

Two changes that arrived together because they are both about a conversation
outliving a single answer.

`conversations` gains a running summary, which is what lets a thread continue
past the old three-turn cutoff without its token cost growing with its length.

`feedback` gains `message_id` and `reason`, which is what turns a thumbs-down
into queryable data: the answer that was judged, why it fell short, and — via
the message's citations, recorded in the existing `source_urls` column — which
documentation pages were implicated.

Note for anyone autogenerating on top of this: Alembic cannot read a pgvector
index and will propose dropping `ix_document_chunks_embedding_hnsw` and
`ix_faq_items_embedding_hnsw`. Delete those drops before applying, every time.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7f1d2b40e51"
down_revision: str | None = "9a26e36a7b99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The event vocabulary before and after this revision. A CHECK constraint has
#: to be dropped and recreated to admit a new member.
_EVENT_TYPES_BEFORE = (
    "faq_impression",
    "faq_selection",
    "faq_resolution",
    "rescue_tool_transition",
    "retrieval",
    "generation",
    "provider_fallback",
    "job_outcome",
    "error",
    "ingestion",
)
_EVENT_TYPES_AFTER = (*_EVENT_TYPES_BEFORE[:3], "chat_resolution", *_EVENT_TYPES_BEFORE[3:])

_FEEDBACK_REASONS = ("incorrect", "incomplete", "irrelevant", "wrong_source", "other")


def _event_type_check(values: Sequence[str]) -> str:
    return "event_type IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.add_column("conversations", sa.Column("history_summary", sa.Text(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("history_summarized_through_ordinal", sa.Integer(), nullable=True),
    )

    op.add_column("feedback", sa.Column("message_id", sa.UUID(), nullable=True))
    op.add_column("feedback", sa.Column("reason", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_feedback_message_id"), "feedback", ["message_id"])
    op.create_foreign_key(
        op.f("fk_feedback_message_id_messages"),
        "feedback",
        "messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_feedback_reason"),
        "feedback",
        "reason IS NULL OR reason IN ("
        + ", ".join(f"'{value}'" for value in _FEEDBACK_REASONS)
        + ")",
    )
    # Chat feedback is read back grouped by outcome over a time window, which is
    # the one query the admin console runs on every load.
    op.create_index(
        "ix_feedback_stage_created_at",
        "feedback",
        ["stage", "created_at"],
    )

    op.drop_constraint(op.f("ck_usage_events_event_type"), "usage_events", type_="check")
    op.create_check_constraint(
        op.f("ck_usage_events_event_type"),
        "usage_events",
        _event_type_check(_EVENT_TYPES_AFTER),
    )


def downgrade() -> None:
    # Rows recorded under the new event type would violate the restored
    # constraint, so they are removed first. They are analytics, not user data.
    op.execute(sa.text("DELETE FROM usage_events WHERE event_type = 'chat_resolution'"))
    op.drop_constraint(op.f("ck_usage_events_event_type"), "usage_events", type_="check")
    op.create_check_constraint(
        op.f("ck_usage_events_event_type"),
        "usage_events",
        _event_type_check(_EVENT_TYPES_BEFORE),
    )

    op.drop_index("ix_feedback_stage_created_at", table_name="feedback")
    op.drop_constraint(op.f("ck_feedback_reason"), "feedback", type_="check")
    op.drop_constraint(op.f("fk_feedback_message_id_messages"), "feedback", type_="foreignkey")
    op.drop_index(op.f("ix_feedback_message_id"), table_name="feedback")
    op.drop_column("feedback", "reason")
    op.drop_column("feedback", "message_id")

    op.drop_column("conversations", "history_summarized_through_ordinal")
    op.drop_column("conversations", "history_summary")
