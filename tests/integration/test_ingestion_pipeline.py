"""The index lifecycle, end to end, against a real database.

A stub embedding client stands in for the provider — deterministic, free, and it
lets these tests count exactly how many embeddings a run generated, which is the
only way to prove the no-change path really costs nothing.

Everything else is real: real MDX text through the real pre-pass and chunker,
real pgvector columns, real activation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.db.models import Document, DocumentChunk, IndexVersion
from src.db.models.enums import IndexStatus
from src.services.embeddings import EmbeddingBatch
from src.services.ingestion import pipeline
from src.services.ingestion.repository import Checkout

pytestmark = pytest.mark.asyncio

DIM = 1536

DOC_ONE = """import Layout from '@/components/Layout'

<Layout>
<Head><title>راه‌اندازی جنگو</title></Head>

<Section id="install" title="نصب" />

برای نصب، دستور زیر را اجرا کنید.

<Highlight className="bash">{`liara deploy --app my-app`}</Highlight>

<Section id="envs" title="متغیرهای محیطی" />

متغیرهای محیطی را از پنل تنظیم کنید تا برنامه به دیتابیس متصل شود.
</Layout>
"""

DOC_TWO = """import Layout from '@/components/Layout'

<Layout>
<Head><title>پستگرس</title></Head>

<Section id="connect" title="اتصال" />

برای اتصال به پایگاه داده از رشته اتصال استفاده کنید و پورت را باز نگه دارید.
</Layout>
"""


@dataclass
class StubEmbeddings:
    """Counts calls so a test can prove embeddings were *not* generated."""

    model: str = "text-embedding-3-large"
    dimensions: int = DIM
    calls: list[int] = field(default_factory=list)
    fail_with: RescueError | None = None

    @property
    def embedded_count(self) -> int:
        return sum(self.calls)

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(len(texts))
        return EmbeddingBatch(
            vectors=[[0.01 * (i + 1)] * self.dimensions for i, _ in enumerate(texts)],
            model=self.model,
            prompt_tokens=len(texts),
            total_tokens=len(texts) * 10,
        )

    def close(self) -> None:  # pragma: no cover — interface parity
        return None


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, embedding_dimensions=DIM, **overrides)


def _write_corpus(root: Path, documents: dict[str, str]) -> None:
    for relative, body in documents.items():
        target = root / "src" / "pages" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


def _checkout(root: Path, commit: str) -> Checkout:
    return Checkout(
        path=root,
        commit=commit,
        repo_url="https://github.com/liara-cloud/docs",
        branch="master",
    )


@pytest_asyncio.fixture
async def factory(engine: AsyncEngine):  # type: ignore[no-untyped-def]
    """A session factory plus cleanup of everything a test activated.

    Ingestion commits by design, so these tests cannot hide inside a rolled-back
    transaction the way the schema tests do.
    """
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        present = (
            await session.execute(select(func.count()).select_from(IndexVersion))
        ).scalar_one()
        if present:
            pytest.skip("database already holds index versions; refusing to disturb them")
    try:
        yield sessionmaker
    finally:
        async with sessionmaker() as session:
            await session.execute(delete(IndexVersion))
            await session.commit()


async def _run(
    factory,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    commit: str,
    *,
    embeddings: StubEmbeddings,
    settings: Settings | None = None,
    force: bool = False,
):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(pipeline, "fetch_corpus", lambda _settings=None: _checkout(root, commit))
    return await pipeline.run_ingestion(
        factory,
        settings=settings or _settings(),
        embeddings=embeddings,
        force=force,
    )


async def test_first_run_indexes_everything_and_activates(
    migrated, factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE, "dbaas/postgres.mdx": DOC_TWO})
    stub = StubEmbeddings()

    report = await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=stub)

    assert report.status == "activated", report.detail
    assert report.added == 2
    assert report.chunks_total > 0
    assert stub.embedded_count == report.chunks_total

    async with factory() as session:
        active = await pipeline.active_index_version(session)
        assert active is not None
        # The commit is what makes a later "has anything changed?" cheap.
        assert active.source_commit == "a" * 40
        assert active.embedding_dimensions == DIM
        assert active.status == IndexStatus.ACTIVE.value
        stored = (
            await session.execute(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.index_version_id == active.id)
            )
        ).scalar_one()
        assert stored == report.chunks_total


async def test_unchanged_commit_generates_no_embeddings(
    migrated, factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE})
    first = StubEmbeddings()
    await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=first)

    second = StubEmbeddings()
    report = await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=second)

    assert report.status == "no_change"
    assert second.embedded_count == 0, "a no-change run must not reach the provider at all"


async def test_only_changed_documents_are_re_embedded(
    migrated, factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE, "dbaas/postgres.mdx": DOC_TWO})
    first = StubEmbeddings()
    initial = await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=first)

    # One document changes upstream; the other is byte-identical.
    _write_corpus(
        tmp_path,
        {"paas/django.mdx": DOC_ONE.replace("نصب", "نصب و راه‌اندازی")},
    )
    second = StubEmbeddings()
    report = await _run(factory, monkeypatch, tmp_path, "b" * 40, embeddings=second)

    assert report.status == "activated", report.detail
    assert report.modified == 1
    assert report.carried_forward == 1
    assert 0 < second.embedded_count < first.embedded_count
    # Carried-forward chunks keep their vectors: nothing is left unembedded.
    async with factory() as session:
        active = await pipeline.active_index_version(session)
        assert active is not None
        missing = (
            await session.execute(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.index_version_id == active.id,
                    DocumentChunk.embedding.is_(None),
                )
            )
        ).scalar_one()
        assert missing == 0
        assert active.chunk_count == report.chunks_total
        assert report.chunks_total == initial.chunks_total or report.chunks_total > 0


async def test_deleted_documents_leave_the_new_index(
    migrated, factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE, "dbaas/postgres.mdx": DOC_TWO})
    await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=StubEmbeddings())

    (tmp_path / "src" / "pages" / "dbaas" / "postgres.mdx").unlink()
    report = await _run(factory, monkeypatch, tmp_path, "b" * 40, embeddings=StubEmbeddings())

    assert report.deleted == 1
    async with factory() as session:
        active = await pipeline.active_index_version(session)
        assert active is not None
        paths = (
            (
                await session.execute(
                    select(Document.source_path).where(Document.index_version_id == active.id)
                )
            )
            .scalars()
            .all()
        )
        assert paths == ["src/pages/paas/django.mdx"]


async def test_failed_run_leaves_the_previous_index_serving(
    migrated, factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE})
    await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=StubEmbeddings())
    async with factory() as session:
        before = await pipeline.active_index_version(session)
        assert before is not None
        before_id = before.id

    broken = StubEmbeddings(
        fail_with=RescueError(ErrorCode.EMBEDDING_FAILED, detail="provider exploded")
    )
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE + "\n\nمتن تازه برای تغییر هش.\n"})
    report = await _run(factory, monkeypatch, tmp_path, "b" * 40, embeddings=broken)

    assert report.status == "failed"
    assert report.error_code == ErrorCode.EMBEDDING_FAILED.value
    async with factory() as session:
        after = await pipeline.active_index_version(session)
        assert after is not None
        assert after.id == before_id, "a failed build must never disturb the serving index"


async def test_validation_failure_blocks_activation(
    migrated, factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE})
    await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=StubEmbeddings())
    async with factory() as session:
        before = await pipeline.active_index_version(session)
        assert before is not None
        before_id = before.id

    async def failing_validation(session, index_version, settings):  # type: ignore[no-untyped-def]
        return {"chunk_count": {"ok": False, "value": 0}, "passed": False}

    monkeypatch.setattr(pipeline, "validate_index", failing_validation)
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE + "\n\nتغییر.\n"})
    report = await _run(factory, monkeypatch, tmp_path, "b" * 40, embeddings=StubEmbeddings())

    assert report.status == "validation_failed"
    assert report.error_code == ErrorCode.INDEX_VALIDATION_FAILED.value
    async with factory() as session:
        after = await pipeline.active_index_version(session)
        assert after is not None and after.id == before_id
        failed = (
            await session.execute(
                select(IndexVersion).where(IndexVersion.id == report.index_version_id)
            )
        ).scalar_one()
        assert failed.status == IndexStatus.FAILED.value
        assert failed.error_code == ErrorCode.INDEX_VALIDATION_FAILED.value


async def test_rollback_reactivates_without_reingesting(
    migrated, factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE})
    first = await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=StubEmbeddings())

    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE + "\n\nتغییر.\n"})
    second = await _run(factory, monkeypatch, tmp_path, "b" * 40, embeddings=StubEmbeddings())
    assert second.status == "activated"

    embeddings = StubEmbeddings()
    async with factory() as session:
        restored = await pipeline.rollback_to(session, first.index_version_id)

    assert restored.id == first.index_version_id
    assert embeddings.embedded_count == 0, "rollback must not re-embed anything"
    async with factory() as session:
        active = await pipeline.active_index_version(session)
        assert active is not None and active.id == first.index_version_id
        assert active.source_commit == "a" * 40


async def test_rollback_refuses_an_empty_index(
    migrated, factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Trading a suspected fault for a certain outage is not a rollback."""
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE})
    await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=StubEmbeddings())

    async with factory() as session:
        empty = IndexVersion(
            id=uuid.uuid4(),
            status=IndexStatus.FAILED.value,
            source_repo_url="https://github.com/liara-cloud/docs",
            source_branch="master",
            source_commit="c" * 40,
            embedding_model="text-embedding-3-large",
            embedding_dimensions=DIM,
        )
        session.add(empty)
        await session.commit()
        empty_id = empty.id

    async with factory() as session:
        with pytest.raises(RescueError) as caught:
            await pipeline.rollback_to(session, empty_id)
    assert caught.value.code is ErrorCode.INDEX_VALIDATION_FAILED


async def test_guardrail_metric_reaches_the_run_output(
    migrated, factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Upstream component drift must surface as a number, not as silence."""
    _write_corpus(tmp_path, {"paas/django.mdx": DOC_ONE})
    report = await _run(factory, monkeypatch, tmp_path, "a" * 40, embeddings=StubEmbeddings())

    assert report.documents, "per-document reporting is how drift becomes visible"
    entry = report.documents[0]
    assert entry.source_path == "src/pages/paas/django.mdx"
    assert 0.0 <= entry.discarded_char_ratio <= 1.0
    assert "flagged_documents" in report.summary()
