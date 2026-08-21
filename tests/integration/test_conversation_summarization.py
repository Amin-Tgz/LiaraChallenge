"""History summarization: a long conversation stays affordable and stays open.

The behavior these tests defend is the one a user notices by its absence. A
fourth question used to be refused; now the turns that fall outside the verbatim
window are condensed and the conversation continues. The condensing is a model
call, so the other half of the contract matters just as much: when that call
fails, the turn still gets answered.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.config import Settings, get_settings
from src.db.models import AnonymousSession, Conversation, Message
from src.db.models.enums import MessageRole
from src.services import summarization
from src.services.summarization import (
    SUMMARY_CONTEXT_PREFIX,
    build_conversation_context,
)

pytestmark = pytest.mark.asyncio


def _settings(**overrides: Any) -> Settings:
    base = get_settings().model_dump()
    base.update(
        {
            "max_history_turns": 1,
            "conversation_summary_trigger_turns": 2,
            "max_conversation_turns": 40,
        }
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


async def _conversation_with_turns(conn: AsyncConnection, pairs: int) -> uuid.UUID:
    session_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    await conn.execute(AnonymousSession.__table__.insert().values(id=session_id))
    await conn.execute(
        Conversation.__table__.insert().values(
            id=conversation_id,
            session_id=session_id,
            initial_question="پرسش ۱",
            initial_question_normalized="پرسش ۱",
            technical_profile={},
        )
    )
    ordinal = 0
    for index in range(1, pairs + 1):
        for role, text in (
            (MessageRole.USER.value, f"پرسش {index}"),
            (MessageRole.ASSISTANT.value, f"پاسخ {index}"),
        ):
            await conn.execute(
                Message.__table__.insert().values(
                    id=uuid.uuid4(),
                    conversation_id=conversation_id,
                    ordinal=ordinal,
                    role=role,
                    content=text,
                    citations=[],
                    images=[],
                )
            )
            ordinal += 1
    return conversation_id


class _FakeSummarizer:
    """Stands in for the gateway call, counting how often it is made."""

    def __init__(self, text: str = "خلاصهٔ نوبت‌های پیشین") -> None:
        self.text = text
        self.calls: list[str] = []

    async def __call__(self, executor, *, previous, turns, settings, telemetry):  # type: ignore[no-untyped-def]
        self.calls.append(str(previous))
        return self.text


async def test_a_short_conversation_is_replayed_verbatim_with_no_model_call(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation_id = await _conversation_with_turns(await db_session.connection(), pairs=1)
    fake = _FakeSummarizer()
    monkeypatch.setattr(summarization, "_summarize", fake)

    context = await build_conversation_context(db_session, conversation_id, settings=_settings())

    assert fake.calls == []
    assert context.summary is None
    assert [turn["content"] for turn in context.turns] == ["پرسش 1", "پاسخ 1"]


async def test_turns_outside_the_window_are_summarized_and_the_summary_is_persisted(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation_id = await _conversation_with_turns(await db_session.connection(), pairs=3)
    fake = _FakeSummarizer()
    monkeypatch.setattr(summarization, "_summarize", fake)

    context = await build_conversation_context(db_session, conversation_id, settings=_settings())

    assert len(fake.calls) == 1
    assert context.summary == "خلاصهٔ نوبت‌های پیشین"
    # Only the most recent pair survives verbatim; the rest became the summary.
    assert [turn["content"] for turn in context.turns] == ["پرسش 3", "پاسخ 3"]

    stored = (
        await db_session.execute(
            select(
                Conversation.history_summary,
                Conversation.history_summarized_through_ordinal,
            ).where(Conversation.id == conversation_id)
        )
    ).one()
    assert stored.history_summary == "خلاصهٔ نوبت‌های پیشین"
    assert stored.history_summarized_through_ordinal == 3


async def test_a_second_pass_summarizes_only_the_new_turns(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each turn is condensed once. Re-reading the transcript every turn would
    reintroduce exactly the cost this replaces."""
    conversation_id = await _conversation_with_turns(await db_session.connection(), pairs=3)
    fake = _FakeSummarizer()
    monkeypatch.setattr(summarization, "_summarize", fake)
    await build_conversation_context(db_session, conversation_id, settings=_settings())

    # Nothing new has happened, so nothing needs summarizing again.
    await build_conversation_context(db_session, conversation_id, settings=_settings())
    assert len(fake.calls) == 1

    # A fourth exchange pushes one more pair out of the window.
    for ordinal, (role, text) in enumerate(
        (
            (MessageRole.USER.value, "پرسش 4"),
            (MessageRole.ASSISTANT.value, "پاسخ 4"),
        ),
        start=6,
    ):
        await db_session.execute(
            Message.__table__.insert().values(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                ordinal=ordinal,
                role=role,
                content=text,
                citations=[],
                images=[],
            )
        )
    await build_conversation_context(db_session, conversation_id, settings=_settings())

    assert len(fake.calls) == 2
    # The second call was handed the first summary, not the whole transcript.
    assert fake.calls[1] == "خلاصهٔ نوبت‌های پیشین"


async def test_the_summary_reaches_the_agent_marked_as_data(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation_id = await _conversation_with_turns(await db_session.connection(), pairs=3)
    monkeypatch.setattr(summarization, "_summarize", _FakeSummarizer())

    context = await build_conversation_context(db_session, conversation_id, settings=_settings())
    messages = context.as_messages()

    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith(SUMMARY_CONTEXT_PREFIX)
    # Recalled conversation text is untrusted input like any other (AGENTS.md
    # rule 4), and the boundary says so in the prompt itself.
    assert "دستور" in SUMMARY_CONTEXT_PREFIX
    assert messages[1]["content"] == "پرسش 3"


async def test_a_failed_summarization_degrades_to_raw_history(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Context is worth having. It is not worth an unanswered question."""
    conversation_id = await _conversation_with_turns(await db_session.connection(), pairs=3)

    async def unavailable(executor, *, previous, turns, settings, telemetry):  # type: ignore[no-untyped-def]
        return previous

    monkeypatch.setattr(summarization, "_summarize", unavailable)

    context = await build_conversation_context(db_session, conversation_id, settings=_settings())

    assert context.summary is None
    assert [turn["content"] for turn in context.turns] == ["پرسش 3", "پاسخ 3"]
    stored = (
        await db_session.execute(
            select(Conversation.history_summary).where(Conversation.id == conversation_id)
        )
    ).scalar_one()
    assert stored is None
