"""Run ingestion outside a request.

    uv run python -m scripts.ingest [--force] [--rollback INDEX_VERSION_ID]

Long-running and operator-invoked: it clones the corpus, parses, embeds, and
activates. Exit status is the contract — a scheduled reindex must be able to
tell "nothing changed" (0) from "the build failed" (1) without parsing output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.db.session import dispose_engine, get_sessionmaker
from src.services.ingestion.pipeline import rollback_to, run_ingestion

logger = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and activate a documentation index.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the upstream commit is unchanged.",
    )
    parser.add_argument(
        "--rollback",
        metavar="INDEX_VERSION_ID",
        help="Reactivate a prior index version instead of ingesting.",
    )
    return parser.parse_args(argv)


async def _main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging()
    settings = get_settings()
    session_factory = get_sessionmaker()

    try:
        if args.rollback:
            async with session_factory() as session:
                target = await rollback_to(session, uuid.UUID(args.rollback))
            print(
                json.dumps(
                    {
                        "status": "rolled_back",
                        "index_version_id": str(target.id),
                        "source_commit": target.source_commit,
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        report = await run_ingestion(session_factory, settings=settings, force=args.force)
        # The guardrail metric belongs in the run's output, not only in a log:
        # a flagged file is how upstream component drift becomes visible.
        print(
            json.dumps(
                {
                    **report.summary(),
                    "flagged_document_paths": report.flagged_documents[:50],
                    "validation": report.validation_report,
                    "detail": report.detail,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if report.status in {"activated", "no_change"} else 1
    finally:
        await dispose_engine()


if __name__ == "__main__":  # pragma: no cover — process entry point
    sys.exit(asyncio.run(_main()))
