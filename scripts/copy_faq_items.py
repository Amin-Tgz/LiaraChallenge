"""Copy generated FAQ entries between databases instead of regenerating them.

FAQ entries are derived from documentation at one upstream commit. Two databases
ingested at the *same* commit hold the same documents, so entries generated
against one are valid against the other — and regenerating them means a model
call per document for an answer that already exists.

What makes the copy safe is a single precondition, checked before anything is
written: **both active indexes must sit on the same `source_commit`.** Copying
across commits would attach answers to documentation that has since moved,
producing citations that resolve to the wrong section — a failure that looks
exactly like a working FAQ until someone follows a link.

Rows carry their own `source_url`, `heading_anchor`, `source_commit`, and
embedding, so citations resolve without the foreign keys. The keys are remapped
anyway: `source_document_id` is what a later incremental generation run uses to
skip unchanged documents, and leaving it null would make that run regenerate the
whole corpus.

Usage::

    # Source is DATABASE_URL, target is LIARA_DATABASE_URL
    uv run python -m scripts.copy_faq_items --dry-run
    uv run python -m scripts.copy_faq_items
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

#: Every column carried across, in one place so an added column fails loudly
#: here rather than being silently dropped from the copy.
_FAQ_COLUMNS = (
    "id",
    "question",
    "question_normalized",
    "answer",
    "source_document_id",
    "source_chunk_id",
    "source_url",
    "heading_anchor",
    "source_commit",
    "source_content_hash",
    "status",
    "is_active",
    "priority",
    "tags",
    "embedding_model",
    "embedding_dimensions",
    "embedding",
    "created_at",
    "updated_at",
)


@dataclass
class CopyReport:
    source_commit: str | None = None
    target_commit: str | None = None
    total: int = 0
    copied: int = 0
    skipped_existing: int = 0
    documents_remapped: int = 0
    chunks_remapped: int = 0
    #: Entries whose source document has no counterpart in the target. Reported
    #: rather than dropped silently — a non-zero count means the two ingestions
    #: disagree about the corpus despite sharing a commit.
    unmatched_documents: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "source_commit": self.source_commit,
            "target_commit": self.target_commit,
            "total": self.total,
            "copied": self.copied,
            "skipped_existing": self.skipped_existing,
            "documents_remapped": self.documents_remapped,
            "chunks_remapped": self.chunks_remapped,
            "unmatched_documents": len(self.unmatched_documents),
        }


class CommitMismatch(RuntimeError):
    """The two databases are not on the same documentation commit."""


async def _active_commit(conn: AsyncConnection) -> str | None:
    return (
        await conn.execute(
            text("SELECT source_commit FROM index_versions WHERE is_active IS TRUE LIMIT 1")
        )
    ).scalar_one_or_none()


async def _document_map(conn: AsyncConnection) -> dict[str, str]:
    """`source_path` → document id, for the active index only."""
    rows = await conn.execute(
        text(
            "SELECT d.source_path, d.id::text FROM documents d "
            "JOIN index_versions v ON v.id = d.index_version_id "
            "WHERE v.is_active IS TRUE"
        )
    )
    return dict(rows.all())


async def _chunk_map(conn: AsyncConnection) -> dict[tuple[str, int], str]:
    """`(document id, ordinal)` → chunk id, for the active index only."""
    rows = await conn.execute(
        text(
            "SELECT c.document_id::text, c.ordinal, c.id::text FROM document_chunks c "
            "JOIN index_versions v ON v.id = c.index_version_id "
            "WHERE v.is_active IS TRUE"
        )
    )
    return {(doc_id, ordinal): chunk_id for doc_id, ordinal, chunk_id in rows}


async def copy_faq_items(
    source: AsyncConnection,
    target: AsyncConnection,
    *,
    dry_run: bool,
) -> CopyReport:
    report = CopyReport()
    report.source_commit = await _active_commit(source)
    report.target_commit = await _active_commit(target)

    if not report.source_commit or not report.target_commit:
        raise CommitMismatch(
            "both databases need an active index version; "
            f"source={report.source_commit!r} target={report.target_commit!r}"
        )
    if report.source_commit != report.target_commit:
        raise CommitMismatch(
            "refusing to copy FAQ entries across different documentation commits: "
            f"source is at {report.source_commit[:8]}, target at {report.target_commit[:8]}. "
            "Answers generated against one commit can cite sections that moved in the other."
        )

    # Identity is by source path, not by row id: the two ingestions minted their
    # own UUIDs for the same documents.
    source_documents = await _document_map(source)
    target_documents = await _document_map(target)
    document_by_id = {doc_id: path for path, doc_id in source_documents.items()}
    source_chunks = await _chunk_map(source)
    chunk_ordinal = {chunk_id: key for key, chunk_id in source_chunks.items()}
    target_chunks = await _chunk_map(target)

    existing = {row[0] for row in await target.execute(text("SELECT id::text FROM faq_items"))}

    rows = await source.execute(
        text(f"SELECT {', '.join(_FAQ_COLUMNS)} FROM faq_items")  # noqa: S608 — fixed list
    )
    insert = text(
        f"INSERT INTO faq_items ({', '.join(_FAQ_COLUMNS)}) VALUES "
        f"({', '.join(':' + name for name in _FAQ_COLUMNS)})"  # noqa: S608 — fixed list
    )

    for row in rows.mappings():
        report.total += 1
        if str(row["id"]) in existing:
            report.skipped_existing += 1
            continue

        values = dict(row)

        source_document_id = values.get("source_document_id")
        target_document_id = None
        if source_document_id is not None:
            path = document_by_id.get(str(source_document_id))
            target_document_id = target_documents.get(path) if path else None
            if target_document_id is not None:
                report.documents_remapped += 1
            elif path:
                report.unmatched_documents.append(path)
        values["source_document_id"] = target_document_id

        source_chunk_id = values.get("source_chunk_id")
        target_chunk_id = None
        if source_chunk_id is not None and target_document_id is not None:
            key = chunk_ordinal.get(str(source_chunk_id))
            if key is not None:
                target_chunk_id = target_chunks.get((target_document_id, key[1]))
                if target_chunk_id is not None:
                    report.chunks_remapped += 1
        values["source_chunk_id"] = target_chunk_id

        # asyncpg wants JSON as text for a JSONB parameter, and the vector
        # column round-trips as its own string form.
        values["tags"] = json.dumps(values["tags"] or [])
        if values.get("embedding") is not None:
            values["embedding"] = str(values["embedding"])

        if not dry_run:
            await target.execute(insert, values)
        report.copied += 1

    return report


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be copied without writing anything.",
    )
    args = parser.parse_args(argv)
    configure_logging()
    settings = get_settings()

    if not settings.liara_database_url:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "detail": "LIARA_DATABASE_URL is not configured; nothing to copy into",
                }
            )
        )
        return 1

    source_engine = create_async_engine(settings.database_url)
    target_engine = create_async_engine(settings.liara_database_url)
    try:
        async with source_engine.connect() as source, target_engine.begin() as target:
            try:
                report = await copy_faq_items(source, target, dry_run=args.dry_run)
            except CommitMismatch as err:
                print(json.dumps({"status": "refused", "detail": str(err)}, ensure_ascii=False))
                return 1
        print(
            json.dumps(
                {"status": "dry_run" if args.dry_run else "copied", **report.summary()},
                ensure_ascii=False,
                indent=2,
            )
        )
        if report.unmatched_documents:
            logger.warning(
                "some FAQ entries had no matching document in the target",
                extra={"count": len(report.unmatched_documents)},
            )
        return 0
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
