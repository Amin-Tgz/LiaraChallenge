"""Operator overrides for tuning values, stored so they survive a restart.

`Settings` reads tuning values from the environment, which is right for anything
chosen once and deployed. But the FAQ similarity threshold is not that kind of
value: it is tuned against live traffic, by watching how many real questions the
FAQ stage resolves, and a tuning loop that costs a redeploy per turn is a tuning
loop nobody runs.

Only overrides live here. An absent row means the environment value stands, so
the deployed configuration is still the default and this table records only the
deliberate departures from it — which is also what makes the audit trail
readable.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB as JSONB_
from sqlalchemy.dialects.postgresql import UUID as UUID_
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base, TimestampMixin


class RuntimeSetting(Base, TimestampMixin):
    """One operator override of an environment-configured tuning value."""

    __tablename__ = "runtime_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID_, primary_key=True, default=uuid.uuid4)

    #: The `Settings` field name this overrides, e.g. `faq_similarity_threshold`.
    #: Unique, because two rows for one field would make the effective value
    #: depend on row order.
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)

    #: JSON rather than text, so a float stays a float. Round-tripping through
    #: a string would put parsing — and its failure modes — on the read path,
    #: which runs on every user question.
    value: Mapped[dict] = mapped_column(JSONB_, nullable=False)

    #: Who changed it. Admin auth is a shared credential, so this is the
    #: username, not an individual — enough to tell an operator change from a
    #: migration, which is the distinction that matters when one is being
    #: blamed for a drop in resolution rate.
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Why. Optional, but a threshold change with no stated reason is one
    #: nobody can safely revert six weeks later.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
