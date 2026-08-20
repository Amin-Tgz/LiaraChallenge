"""The normalizer, checked through Postgres rather than in isolation.

The unit tests prove the function folds correctly and the structural guard
proves no second implementation exists. This proves the part neither can: that
text stored through `text_normalized` is reachable by a query normalized the
same way, using the real `to_tsvector('simple', …)` index the lexical retrieval
path will use.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.config import get_settings
from src.core.normalization import normalize_query, normalize_text
from src.db.models.enums import IndexStatus

pytestmark = pytest.mark.asyncio

ZWNJ = chr(0x200C)

#: Documentation prose on the left, the way a stuck user types it on the right.
#: Each pair differs by exactly one thing the normalizer is responsible for.
DOCUMENT_AND_QUERY = [
    (f"برای دیپلوی، دستور liara deploy اجرا می{ZWNJ}شود.", "می شود"),
    ("دیتابیس PostgreSQL را می‌سازیم.", "ديتابيس"),
    ("پلن ۲ گیگابایتی مناسب است.", "پلن 2"),
    ("خطای 503 یعنی سرویس در دسترس نیست.", "خطاي ۵۰۳؟"),
    ("با Docker Compose اجرا کنید.", "docker compose"),
]


async def _seed_chunk(conn: AsyncConnection, body: str) -> uuid.UUID:
    settings = get_settings()
    index_version_id, document_id, chunk_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO index_versions (id, status, source_repo_url, source_branch, "
            "source_commit, ingest_sections, embedding_model, embedding_dimensions, "
            "normalizer_version, document_count, chunk_count) "
            "VALUES (:id, :status, 'https://github.com/liara-cloud/docs', 'master', "
            ":commit, '*', :model, :dim, 1, 1, 1)"
        ),
        {
            "id": index_version_id,
            "status": IndexStatus.READY.value,
            "commit": "0" * 40,
            "model": settings.embedding_model,
            "dim": settings.embedding_dimensions,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO documents (id, index_version_id, source_path, source_url, "
            "source_commit, title, section, breadcrumbs, language, content_hash, "
            "source_char_count, discarded_char_ratio, flagged_for_review) "
            "VALUES (:id, :iv, 'src/pages/paas/about.mdx', "
            "'https://docs.liara.ir/paas/about', :commit, 'about', 'paas', :crumbs, "
            "'fa', :hash, 100, 0.0, false)"
        ),
        {
            "id": document_id,
            "iv": index_version_id,
            "commit": "0" * 40,
            "crumbs": json.dumps(["paas"]),
            "hash": "0" * 64,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO document_chunks (id, index_version_id, document_id, ordinal, text, "
            "text_normalized, token_count, source_url, source_path, source_commit, "
            "breadcrumbs, content_type, code_languages, language, images, extra_metadata, "
            "embedding_model, embedding_dimensions) "
            "VALUES (:id, :iv, :doc, 0, :raw, :norm, 10, "
            "'https://docs.liara.ir/paas/about', 'src/pages/paas/about.mdx', :commit, "
            "'[]'::jsonb, 'prose', '[]'::jsonb, 'fa', '[]'::jsonb, '{}'::jsonb, :model, :dim)"
        ),
        {
            "id": chunk_id,
            "iv": index_version_id,
            "doc": document_id,
            "raw": body,
            # The index path calls the shared function — never a local variant.
            "norm": normalize_text(body),
            "commit": "0" * 40,
            "model": settings.embedding_model,
            "dim": settings.embedding_dimensions,
        },
    )
    return chunk_id


@pytest.mark.parametrize(("body", "question"), DOCUMENT_AND_QUERY)
async def test_query_matches_document_stored_under_the_same_rules(
    migrated: AsyncConnection, body: str, question: str
) -> None:
    conn = migrated
    chunk_id = await _seed_chunk(conn, body)

    # The query path calls the same function, so a spelling difference between
    # the user and the documentation cannot survive to the search.
    normalized_question = normalize_query(question)
    matched = (
        await conn.execute(
            text(
                "SELECT id FROM document_chunks "
                "WHERE id = :id AND search_vector @@ plainto_tsquery('simple', :q)"
            ),
            {"id": chunk_id, "q": normalized_question},
        )
    ).scalar()

    assert matched == chunk_id, (
        f"question {question!r} normalized to {normalized_question!r} did not reach "
        f"content stored as {normalize_text(body)!r}"
    )


async def test_raw_question_would_have_missed(migrated: AsyncConnection) -> None:
    """The failure this whole component prevents, demonstrated once.

    Searching with the user's untouched spelling against normalized content
    returns nothing — no error, no log line, just an answer that never arrives.
    """
    conn = migrated
    body = "دیتابیس PostgreSQL را می‌سازیم."
    chunk_id = await _seed_chunk(conn, body)
    raw_question = "ديتابيس"

    unnormalized_hit = (
        await conn.execute(
            text(
                "SELECT id FROM document_chunks "
                "WHERE id = :id AND search_vector @@ plainto_tsquery('simple', :q)"
            ),
            {"id": chunk_id, "q": raw_question},
        )
    ).scalar()
    normalized_hit = (
        await conn.execute(
            text(
                "SELECT id FROM document_chunks "
                "WHERE id = :id AND search_vector @@ plainto_tsquery('simple', :q)"
            ),
            {"id": chunk_id, "q": normalize_query(raw_question)},
        )
    ).scalar()

    assert unnormalized_hit is None
    assert normalized_hit == chunk_id
