"""Schema guarantees that only a real Postgres can demonstrate.

Two things are checked here because their failure modes are silent:

* an unused HNSW index — similarity search still returns correct rows, just by
  scanning every chunk, so nothing errors and latency degrades with corpus size;
* a missing idempotency constraint — a duplicate submission quietly becomes a
  second job, and the user pays twice for one question.
"""

from __future__ import annotations

import json
import random
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.config import get_settings
from src.db.models.enums import IndexStatus, JobStatus

pytestmark = pytest.mark.asyncio

DIM = get_settings().embedding_dimensions
#: Enough rows that a sequential scan is not trivially the cheapest plan.
CHUNK_ROWS = 2000


def _vector(rng: random.Random) -> str:
    return "[" + ",".join(f"{rng.uniform(-1, 1):.6f}" for _ in range(DIM)) + "]"


async def _seed_index_version(conn: AsyncConnection) -> uuid.UUID:
    index_version_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO index_versions (id, status, source_repo_url, source_branch, "
            "source_commit, ingest_sections, embedding_model, embedding_dimensions, "
            "normalizer_version, document_count, chunk_count) "
            "VALUES (:id, :status, :repo, :branch, :commit, '*', :model, :dim, 1, 1, :chunks)"
        ),
        {
            "id": index_version_id,
            "status": IndexStatus.READY.value,
            "repo": "https://github.com/liara-cloud/docs",
            "branch": "master",
            "commit": "0" * 40,
            "model": "text-embedding-3-large",
            "dim": DIM,
            "chunks": CHUNK_ROWS,
        },
    )
    return index_version_id


async def _seed_document(conn: AsyncConnection, index_version_id: uuid.UUID) -> uuid.UUID:
    document_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO documents (id, index_version_id, source_path, source_url, "
            "source_commit, title, section, breadcrumbs, language, content_hash, "
            "source_char_count, discarded_char_ratio, flagged_for_review) "
            "VALUES (:id, :iv, :path, :url, :commit, :title, :section, :crumbs, 'fa', "
            ":hash, 100, 0.0, false)"
        ),
        {
            "id": document_id,
            "iv": index_version_id,
            "path": "src/pages/paas/about.mdx",
            "url": "https://docs.liara.ir/paas/about",
            "commit": "0" * 40,
            "title": "درباره پلتفرم",
            "section": "paas",
            "crumbs": json.dumps(["paas", "about"]),
            "hash": "0" * 64,
        },
    )
    return document_id


async def test_similarity_search_uses_the_hnsw_index(migrated: AsyncConnection) -> None:
    conn = migrated
    rng = random.Random(20260820)
    index_version_id = await _seed_index_version(conn)
    document_id = await _seed_document(conn, index_version_id)

    rows = [
        {
            "id": uuid.uuid4(),
            "iv": index_version_id,
            "doc": document_id,
            "ordinal": i,
            "text": f"chunk {i}",
            "norm": f"chunk {i}",
            "url": "https://docs.liara.ir/paas/about",
            "path": "src/pages/paas/about.mdx",
            "commit": "0" * 40,
            "model": "text-embedding-3-large",
            "dim": DIM,
            "embedding": _vector(rng),
        }
        for i in range(CHUNK_ROWS)
    ]
    await conn.execute(
        text(
            "INSERT INTO document_chunks (id, index_version_id, document_id, ordinal, text, "
            "text_normalized, token_count, source_url, source_path, source_commit, "
            "breadcrumbs, content_type, code_languages, language, images, extra_metadata, "
            "embedding_model, embedding_dimensions, embedding) "
            "VALUES (:id, :iv, :doc, :ordinal, :text, :norm, 10, :url, :path, :commit, "
            "'[]'::jsonb, 'prose', '[]'::jsonb, 'fa', '[]'::jsonb, '{}'::jsonb, "
            ":model, :dim, CAST(:embedding AS vector))"
        ),
        rows,
    )
    await conn.execute(text("ANALYZE document_chunks"))
    # This test database may also hold the real active corpus. Its btree filter
    # can be cheaper for this synthetic index version than traversing the
    # global HNSW index, even though the HNSW index itself is healthy. Disable
    # the competing scan plans locally so this assertion tests index usability
    # rather than the planner's cost estimate for fixture-only data.
    await conn.execute(text("SET LOCAL enable_seqscan = off"))
    await conn.execute(text("SET LOCAL enable_bitmapscan = off"))

    query_vector = _vector(rng)
    plan = (
        await conn.execute(
            text(
                "EXPLAIN (FORMAT JSON) "
                "SELECT id, 1 - (embedding <=> CAST(:q AS vector)) AS similarity "
                "FROM document_chunks WHERE index_version_id = :iv "
                "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
            ),
            {"q": query_vector, "iv": index_version_id, "k": get_settings().retrieval_top_k},
        )
    ).scalar()

    rendered = json.dumps(plan)
    assert "ix_document_chunks_embedding_hnsw" in rendered, (
        "similarity search fell back to a scan; the HNSW index is not being used:\n" + rendered
    )
    assert '"Node Type": "Seq Scan"' not in rendered, rendered


async def test_similarity_is_the_exposed_unit(migrated: AsyncConnection) -> None:
    """`<=>` returns cosine distance; every surface must see `1 - distance`."""
    conn = migrated
    same = (
        await conn.execute(
            text("SELECT 1 - (CAST(:a AS vector) <=> CAST(:b AS vector))"),
            {"a": "[1,0,0]", "b": "[1,0,0]"},
        )
    ).scalar()
    opposite = (
        await conn.execute(
            text("SELECT 1 - (CAST(:a AS vector) <=> CAST(:b AS vector))"),
            {"a": "[1,0,0]", "b": "[-1,0,0]"},
        )
    ).scalar()
    assert same == pytest.approx(1.0)
    assert opposite == pytest.approx(-1.0)


async def test_duplicate_idempotency_key_is_refused(migrated: AsyncConnection) -> None:
    conn = migrated
    session_id, conversation_id = uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        text("INSERT INTO sessions (id) VALUES (:id)"),
        {"id": session_id},
    )
    await conn.execute(
        text(
            "INSERT INTO conversations (id, session_id, initial_question, "
            "initial_question_normalized, technical_profile) "
            "VALUES (:id, :session, :q, :q, '{}'::jsonb)"
        ),
        {"id": conversation_id, "session": session_id, "q": "چطور اپ را دیپلوی کنم؟"},
    )

    key = f"idem-{uuid.uuid4()}"
    insert = text(
        "INSERT INTO request_jobs (id, conversation_id, idempotency_key, status, question, "
        "transitions, attempt, max_attempts) "
        "VALUES (:id, :conversation, :key, :status, :q, '[]'::jsonb, 0, 3)"
    )
    params = {
        "conversation": conversation_id,
        "key": key,
        "status": JobStatus.QUEUED.value,
        "q": "چطور اپ را دیپلوی کنم؟",
    }
    await conn.execute(insert, {"id": uuid.uuid4(), **params})

    # Resubmission must not become a second job — that is what makes reload
    # during generation safe.
    with pytest.raises(IntegrityError):
        await conn.execute(insert, {"id": uuid.uuid4(), **params})


async def test_only_one_index_version_can_be_active(migrated: AsyncConnection) -> None:
    """Activation is a single-row flip; two active versions would split retrieval."""
    conn = migrated
    first = await _seed_index_version(conn)
    second = await _seed_index_version(conn)
    active_exists = (
        await conn.execute(text("SELECT EXISTS(SELECT 1 FROM index_versions WHERE is_active)"))
    ).scalar_one()
    if not active_exists:
        await conn.execute(
            text("UPDATE index_versions SET is_active = TRUE WHERE id = :id"), {"id": first}
        )
    with pytest.raises(IntegrityError):
        await conn.execute(
            text("UPDATE index_versions SET is_active = TRUE WHERE id = :id"), {"id": second}
        )
