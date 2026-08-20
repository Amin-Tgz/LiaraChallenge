"""Generate and embed FAQ questions for the active documentation index.

    uv run python -m scripts.generate_faq

Each document commits independently, so a retry skips completed source hashes
instead of paying for them again. Provider calls run concurrently up to the
configured limit; FAQ-question embeddings are generated after extraction.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import asdict

from sqlalchemy import select

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.models import Document, IndexVersion
from src.db.session import dispose_engine, get_sessionmaker
from src.services.embeddings import EmbeddingClient
from src.services.faq import GatewayFaqGenerator, embed_faq_questions, generate_document_faqs

logger = get_logger(__name__)


async def _main() -> int:
    configure_logging()
    settings = get_settings()
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        document_ids = list(
            (
                await session.execute(
                    select(Document.id)
                    .join(IndexVersion, IndexVersion.id == Document.index_version_id)
                    .where(IndexVersion.is_active.is_(True))
                    .order_by(Document.source_path)
                )
            )
            .scalars()
            .all()
        )

    queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
    for document_id in document_ids:
        queue.put_nowait(document_id)
    reports: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []

    async def worker() -> None:
        generator = GatewayFaqGenerator(settings)
        try:
            while True:
                try:
                    document_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    async with session_factory() as session:
                        report = await generate_document_faqs(
                            session,
                            document_id,
                            generator,
                            settings=settings,
                        )
                        await session.commit()
                    reports.append(asdict(report))
                except Exception as err:  # noqa: BLE001 - failure is reported per document
                    failures.append({"document_id": str(document_id), "cause": type(err).__name__})
                    logger.exception(
                        "FAQ document generation failed",
                        extra={"document_id": str(document_id)},
                    )
                finally:
                    queue.task_done()
        finally:
            generator.close()

    worker_count = min(settings.faq_generation_concurrency, len(document_ids))
    await asyncio.gather(*(worker() for _ in range(worker_count)))

    with EmbeddingClient(settings) as embeddings:
        async with session_factory() as session:
            embedding_report = await embed_faq_questions(
                session,
                embeddings,
                settings=settings,
            )
            await session.commit()

    summary = {
        "documents": len(document_ids),
        "generated_documents": sum(not report["skipped"] for report in reports),
        "skipped_documents": sum(bool(report["skipped"]) for report in reports),
        "accepted_items": sum(int(report["accepted"]) for report in reports),
        "rejected_items": sum(int(report["rejected"]) for report in reports),
        "failed_documents": len(failures),
        "failures": failures[:50],
        "embedding": asdict(embedding_report),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 1 if failures else 0


async def _entrypoint() -> int:
    try:
        return await _main()
    finally:
        await dispose_engine()


if __name__ == "__main__":  # pragma: no cover - operator entry point
    sys.exit(asyncio.run(_entrypoint()))
