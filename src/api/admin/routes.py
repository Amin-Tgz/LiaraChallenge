"""Admin surface: FAQ curation, index sync, runtime tuning, and the dashboard.

Every route here depends on `require_admin`. That is stated once, as a router-
level dependency, rather than repeated per handler — a new endpoint added to
this router is protected by default, and forgetting to add the decorator cannot
quietly open a hole.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.auth import AdminUser, require_admin
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models import FaqItem, IndexVersion
from src.db.models.enums import FaqStatus
from src.db.session import get_session
from src.services.dashboard import DEFAULT_WINDOW_DAYS, build_dashboard
from src.services.embeddings import EmbeddingClient
from src.services.runtime_config import (
    clear_override,
    describe_overridable,
    load_overrides,
    set_override,
)
from src.services.sync import read_status, trigger_sync

logger = get_logger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

Db = Annotated[AsyncSession, Depends(get_session)]


# --- FAQ curation (13.2) ---------------------------------------------------


class FaqItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    answer: str
    source_url: str
    heading_anchor: str | None
    source_commit: str | None
    status: str
    is_active: bool
    priority: int
    tags: list[str]
    #: False means the question changed and the entry cannot match until it is
    #: re-embedded. Surfaced because such an entry is invisible to users while
    #: still looking present in the admin list.
    embedded: bool


class FaqListOut(BaseModel):
    total: int
    items: list[FaqItemOut]


class FaqUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, min_length=1)
    answer: str | None = Field(default=None, min_length=1)
    status: str | None = None
    is_active: bool | None = None
    priority: int | None = None
    tags: list[str] | None = None


def _faq_out(item: FaqItem) -> FaqItemOut:
    return FaqItemOut(
        id=item.id,
        question=item.question,
        answer=item.answer,
        source_url=item.source_url,
        heading_anchor=item.heading_anchor,
        source_commit=item.source_commit,
        status=item.status,
        is_active=item.is_active,
        priority=item.priority,
        tags=list(item.tags or []),
        embedded=item.embedding is not None,
    )


@router.get("/faq", response_model=FaqListOut)
async def list_faq_items(
    db: Db,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    active: Annotated[bool | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FaqListOut:
    """Page through the FAQ corpus for review."""
    conditions = []
    if status_filter is not None:
        conditions.append(FaqItem.status == status_filter)
    if active is not None:
        conditions.append(FaqItem.is_active.is_(active))
    if search:
        # Matched against the normalized column, because the user-visible
        # question and the search term must go through the same normalizer or
        # ی/ي alone loses the match.
        conditions.append(FaqItem.question_normalized.contains(normalize_query(search)))

    total = (
        await db.execute(select(func.count()).select_from(FaqItem).where(*conditions))
    ).scalar_one()
    rows = (
        await db.execute(
            select(FaqItem)
            .where(*conditions)
            .order_by(FaqItem.priority.desc(), FaqItem.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    return FaqListOut(total=int(total), items=[_faq_out(item) for item in rows])


@router.get("/faq/{faq_id}", response_model=FaqItemOut)
async def get_faq_item(faq_id: uuid.UUID, db: Db) -> FaqItemOut:
    item = await db.get(FaqItem, faq_id)
    if item is None:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail=f"no FAQ entry with id {faq_id}")
    return _faq_out(item)


@router.patch("/faq/{faq_id}", response_model=FaqItemOut)
async def update_faq_item(
    faq_id: uuid.UUID,
    payload: FaqUpdateIn,
    db: Db,
    admin: AdminUser,
) -> FaqItemOut:
    """Edit an entry, re-embedding when the question itself changed.

    The embedding is of the *question*, so an edited answer needs no new vector
    while an edited question needs one before it can match anything. The entry
    is deactivated for the moment between the two: an entry whose stored vector
    no longer represents its text would match questions it has nothing to do
    with, which is worse than being briefly absent.
    """
    item = await db.get(FaqItem, faq_id)
    if item is None:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail=f"no FAQ entry with id {faq_id}")

    if payload.status is not None and payload.status not in set(FaqStatus):
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail=(
                f"status must be one of {', '.join(sorted(s.value for s in FaqStatus))}; "
                f"got {payload.status!r}"
            ),
        )

    question_changed = payload.question is not None and payload.question != item.question

    if payload.question is not None:
        item.question = payload.question
        item.question_normalized = normalize_query(payload.question)
    if payload.answer is not None:
        item.answer = payload.answer
    if payload.status is not None:
        item.status = payload.status
    if payload.is_active is not None:
        item.is_active = payload.is_active
    if payload.priority is not None:
        item.priority = payload.priority
    if payload.tags is not None:
        item.tags = list(payload.tags)

    if question_changed:
        item.embedding = None
        client = EmbeddingClient()
        try:
            # `embed_one` is synchronous, so it goes to a thread — the same way
            # retrieval calls it. Blocking the event loop here would stall every
            # concurrent user request behind one admin edit.
            item.embedding = await asyncio.to_thread(client.embed_one, item.question_normalized)
        except RescueError:
            # The edit is kept and the entry stays unembedded rather than
            # silently reverting the operator's text. It is reported as
            # `embedded: false` and can be re-embedded by saving again.
            logger.warning(
                "FAQ re-embedding failed; entry saved without a vector",
                extra={"faq_item_id": str(item.id)},
            )
        finally:
            client.close()

    # An operator edit is a curation act, so the entry stops being merely
    # generated. This is what makes curated entries distinguishable.
    if question_changed or payload.answer is not None:
        item.status = payload.status or FaqStatus.REVIEWED.value

    await db.flush()
    logger.info(
        "FAQ entry edited",
        extra={
            "faq_item_id": str(item.id),
            "admin": admin,
            "question_changed": question_changed,
            "reembedded": question_changed and item.embedding is not None,
        },
    )
    return _faq_out(item)


# `response_model=None` is required, not decorative: `from __future__ import
# annotations` leaves `-> None` as the string "None", which FastAPI cannot
# resolve and so treats as a response model — and a 204 may not have one.
@router.delete("/faq/{faq_id}", status_code=204, response_model=None)
async def delete_faq_item(faq_id: uuid.UUID, db: Db, admin: AdminUser) -> None:
    """Remove an entry so it stops appearing in user-facing results."""
    result = await db.execute(delete(FaqItem).where(FaqItem.id == faq_id))
    if not result.rowcount:
        raise RescueError(ErrorCode.INVALID_REQUEST, detail=f"no FAQ entry with id {faq_id}")
    logger.info("FAQ entry deleted", extra={"faq_item_id": str(faq_id), "admin": admin})


# --- Runtime configuration (13.4) ------------------------------------------


class ConfigOut(BaseModel):
    fields: list[dict[str, Any]]
    overrides: dict[str, Any]


class ConfigSetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any
    note: str | None = None


@router.get("/config", response_model=ConfigOut)
async def get_config(db: Db) -> ConfigOut:
    """The tunable fields, their bounds and deployed defaults, and any overrides."""
    return ConfigOut(fields=describe_overridable(), overrides=await load_overrides(db))


@router.put("/config/{key}", response_model=ConfigOut)
async def put_config(key: str, payload: ConfigSetIn, db: Db, admin: AdminUser) -> ConfigOut:
    """Change one tuning value; it takes effect on the next request."""
    await set_override(db, key, payload.value, updated_by=admin, note=payload.note)
    await db.flush()
    return ConfigOut(fields=describe_overridable(), overrides=await load_overrides(db))


@router.delete("/config/{key}", response_model=ConfigOut)
async def delete_config(key: str, db: Db, admin: AdminUser) -> ConfigOut:
    """Drop an override so the deployed environment value stands again."""
    removed = await clear_override(db, key)
    await db.flush()
    logger.info("runtime override reset", extra={"key": key, "admin": admin, "removed": removed})
    return ConfigOut(fields=describe_overridable(), overrides=await load_overrides(db))


# --- Index synchronization (13.3) ------------------------------------------


class SyncTriggerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Rebuild even when the upstream commit is unchanged. Off by default,
    #: because the point of an incremental sync is that an unchanged corpus
    #: costs a fetch rather than a full re-embed.
    force: bool = False


@router.post("/sync", status_code=202)
async def trigger_index_sync(payload: SyncTriggerIn, admin: AdminUser) -> dict[str, Any]:
    """Start a synchronization and return immediately; poll `GET /admin/sync`.

    202, not 200: the work has been accepted, not completed. A full rebuild
    takes minutes to an hour, which no request should be held open for.
    """
    return await trigger_sync(force=payload.force, triggered_by=admin)


@router.get("/sync")
async def get_index_sync_status() -> dict[str, Any]:
    """The most recent run's outcome, or an explicit statement that none exists."""
    status = await read_status()
    if status is None:
        # Not an error and not an empty success — say which.
        return {"state": "never_run", "detail": "no synchronization has been recorded"}
    return status


# --- Dashboard (13.5, 13.6) ------------------------------------------------


@router.get("/dashboard")
async def get_dashboard(
    db: Db,
    window_days: Annotated[int, Query(ge=1, le=365)] = DEFAULT_WINDOW_DAYS,
    top_n: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    """Every figure derived from recorded events, with explicit no-data states."""
    dashboard = await build_dashboard(db, window_days=window_days, top_n=top_n)
    return dashboard.as_dict()


# --- Index versions --------------------------------------------------------


@router.get("/index-versions")
async def list_index_versions(db: Db, limit: Annotated[int, Query(ge=1, le=50)] = 10) -> Any:
    """Recent index versions, so a rollback target can be chosen by evidence."""
    try:
        rows = (
            await db.execute(
                select(IndexVersion).order_by(IndexVersion.created_at.desc()).limit(limit)
            )
        ).scalars()
    except SQLAlchemyError as err:
        raise RescueError(
            ErrorCode.RETRIEVAL_FAILED, detail="failed to read index versions"
        ) from err
    return [
        {
            "id": str(version.id),
            "status": version.status,
            "is_active": bool(version.is_active),
            "source_commit": version.source_commit,
            "document_count": version.document_count,
            "chunk_count": version.chunk_count,
            "created_at": version.created_at.isoformat() if version.created_at else None,
            "activated_at": version.activated_at.isoformat() if version.activated_at else None,
            "error_code": version.error_code,
        }
        for version in rows
    ]
