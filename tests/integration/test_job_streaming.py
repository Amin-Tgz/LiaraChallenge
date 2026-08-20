"""§10.3, §10.4 — the worker-to-client relay and reconnection from an offset."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import ErrorCode, RescueError
from src.db.models.conversation import AnonymousSession, Conversation
from src.db.models.enums import JobStatus
from src.db.session import get_session
from src.main import create_app
from src.services.agent import AgentCitation, AgentTurnResult
from src.services.job_runner import process_job
from src.services.jobs import create_or_get_job

pytestmark = pytest.mark.asyncio

ANSWER = "برای استقرار برنامه روی لیارا از دستور liara deploy استفاده کنید و پورت را تنظیم کنید."


class StubAgent:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    async def run(self, executor: Any, **kwargs: Any) -> AgentTurnResult:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _answer() -> AgentTurnResult:
    return AgentTurnResult(
        content=ANSWER,
        messages=(),
        tool_calls=1,
        rewrites=0,
        total_tokens=200,
        citations=(
            AgentCitation(
                evidence_id="e1",
                url="https://docs.liara.ir/paas/deploy#deploy",
                page_title="استقرار برنامه",
                section_title="deploy",
                source_commit="b" * 40,
            ),
        ),
    )


async def _seed(session: AsyncSession) -> tuple[AnonymousSession, Conversation]:
    anon = AnonymousSession(id=uuid.uuid4())
    session.add(anon)
    await session.flush()
    conversation = Conversation(
        session_id=anon.id,
        initial_question="چطور برنامه را مستقر کنم؟",
        initial_question_normalized="چطور برنامه را مستقر کنم؟",
        technical_profile={},
    )
    session.add(conversation)
    await session.flush()
    return anon, conversation


async def _client(app: Any, db_session: AsyncSession, anon: AnonymousSession) -> httpx.AsyncClient:
    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={"rescue_session": str(anon.id)},
    )
    return client


def _parse_sse(chunk: str) -> list[dict[str, Any]]:
    """Parse an SSE payload into `{id, event, data}` records."""
    frames: list[dict[str, Any]] = []
    for block in chunk.split("\n\n"):
        record: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("id: "):
                record["id"] = line[4:]
            elif line.startswith("event: "):
                record["event"] = line[7:]
            elif line.startswith("data: "):
                record["data"] = json.loads(line[6:])
        if "event" in record:
            frames.append(record)
    return frames


async def test_content_produced_in_the_worker_reaches_an_sse_client(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """§10.3 — the relay actually carries the worker's output to a browser."""
    anon, conversation = await _seed(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    # The worker side: produce the answer onto the relay.
    await process_job(db_session, redis_client, job, StubAgent(_answer()))

    app = create_app()
    client = await _client(app, db_session, anon)
    try:
        response = await client.get(f"/api/v1/chat/jobs/{job.id}/events")
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # Without this Liara's router buffers the whole body and the client sees
    # nothing until generation ends.
    assert response.headers["x-accel-buffering"] == "no"

    frames = _parse_sse(response.text)
    events = [frame["event"] for frame in frames]
    assert "status" in events
    assert "delta" in events
    assert events[-1] == "final"

    streamed = "".join(f["data"]["text"] for f in frames if f["event"] == "delta")
    assert streamed == ANSWER

    final = frames[-1]["data"]
    assert final["answer"] == ANSWER
    assert final["citations"][0]["url"].endswith("#deploy")


async def test_reconnecting_from_an_offset_receives_only_what_it_missed(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """§10.4 — a client that drops mid-stream resumes rather than restarts."""
    anon, conversation = await _seed(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    await process_job(db_session, redis_client, job, StubAgent(_answer()))

    app = create_app()
    client = await _client(app, db_session, anon)
    try:
        whole = _parse_sse((await client.get(f"/api/v1/chat/jobs/{job.id}/events")).text)
        # Pretend the connection dropped after the first delta.
        first_delta = next(i for i, f in enumerate(whole) if f["event"] == "delta")
        resume_from = whole[first_delta]["id"]

        resumed = await client.get(
            f"/api/v1/chat/jobs/{job.id}/events",
            headers={"Last-Event-ID": resume_from},
        )
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    frames = _parse_sse(resumed.text)
    offsets = [frame["id"] for frame in frames]
    # Nothing already delivered is repeated, and the tail still arrives.
    assert resume_from not in offsets
    assert frames[-1]["event"] == "final"

    missed = "".join(f["data"]["text"] for f in frames if f["event"] == "delta")
    delivered_before = whole[first_delta]["data"]["text"]
    assert delivered_before + missed == ANSWER


async def test_a_failed_job_streams_its_own_cause(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """A failure names why, in Persian. Never a generic 'something went wrong'."""
    anon, conversation = await _seed(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    job.max_attempts = 1
    await db_session.flush()
    await process_job(
        db_session,
        redis_client,
        job,
        StubAgent(RescueError(ErrorCode.ALL_PROVIDERS_UNAVAILABLE, detail="both down")),
    )

    app = create_app()
    client = await _client(app, db_session, anon)
    try:
        response = await client.get(f"/api/v1/chat/jobs/{job.id}/events")
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    frames = _parse_sse(response.text)
    assert frames[-1]["event"] == "error"
    assert frames[-1]["data"]["error_code"] == ErrorCode.ALL_PROVIDERS_UNAVAILABLE.value
    assert frames[-1]["data"]["message"].strip()
    assert job.status == JobStatus.FAILED


async def test_reload_during_generation_restores_state_without_regenerating(
    db_session: AsyncSession,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§11.9 — the conversation and job survive a refresh."""
    anon, conversation = await _seed(db_session)
    job, _ = await create_or_get_job(
        db_session,
        conversation_id=conversation.id,
        question=conversation.initial_question,
        idempotency_key=uuid.uuid4().hex,
    )
    await db_session.commit()

    app = create_app()
    client = await _client(app, db_session, anon)
    try:
        detail = await client.get(f"/api/v1/chat/conversations/{conversation.id}")
        listing = await client.get("/api/v1/chat/conversations")
        status = await client.get(f"/api/v1/chat/jobs/{job.id}")
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    assert detail.status_code == 200
    assert detail.json()["initial_question"] == conversation.initial_question
    assert [j["id"] for j in detail.json()["jobs"]] == [str(job.id)]

    assert listing.status_code == 200
    assert str(conversation.id) in [row["id"] for row in listing.json()]

    assert status.status_code == 200
    assert status.json()["status"] == JobStatus.QUEUED


async def test_a_conversation_from_another_session_is_not_readable(
    db_session: AsyncSession,
) -> None:
    """Ownership is enforced, and a foreign id is indistinguishable from a missing one."""
    _, conversation = await _seed(db_session)
    stranger = AnonymousSession(id=uuid.uuid4())
    db_session.add(stranger)
    await db_session.flush()

    app = create_app()
    client = await _client(app, db_session, stranger)
    try:
        response = await client.get(f"/api/v1/chat/conversations/{conversation.id}")
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.INVALID_REQUEST.value


async def test_an_oversized_question_is_refused_with_its_limit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§14.2 — the rejection states the limit rather than failing opaquely."""
    anon, _ = await _seed(db_session)

    # Nothing may reach a live worker from a test.
    monkeypatch.setattr("src.api.v1.chat.enqueue", _no_enqueue)

    app = create_app()
    client = await _client(app, db_session, anon)
    try:
        response = await client.post(
            "/api/v1/chat/conversations",
            json={"question": "ب" * 5000},
        )
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    assert response.status_code == 413
    assert response.json()["error"]["code"] == ErrorCode.INPUT_TOO_LARGE.value


async def test_posting_the_same_idempotency_key_twice_returns_one_job(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§10.5 over HTTP — both submissions observe the same job."""
    anon, _ = await _seed(db_session)
    monkeypatch.setattr("src.api.v1.chat.enqueue", _no_enqueue)
    key = uuid.uuid4().hex

    app = create_app()
    client = await _client(app, db_session, anon)
    try:
        first = await client.post(
            "/api/v1/chat/conversations",
            json={"question": "چطور دیتابیس بسازم؟", "idempotency_key": key},
        )
        conversation_id = first.json()["conversation_id"]
        second = await client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"question": "چطور دیتابیس بسازم؟", "idempotency_key": key},
        )
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["job"]["id"] == second.json()["job"]["id"]


async def _no_enqueue(*args: Any, **kwargs: Any) -> None:
    """Keeps test-created jobs away from the live compose worker."""
    return None
