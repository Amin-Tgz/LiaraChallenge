"""The chat agent's complete and immutable native-tool allowlist."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.db.models import Document, DocumentChunk, IndexVersion
from src.services.faq import FaqEmbeddingProvider, match_faqs
from src.services.retrieval import RetrievalIntent, RetrievalTelemetry, search_documentation

Executor = AsyncSession | AsyncConnection


class AgentToolName(StrEnum):
    SEARCH_DOCS = "search_docs"
    READ_DOC = "read_doc"
    SEARCH_RELATED_QUESTIONS = "search_related_questions"


class _StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchDocsInput(_StrictToolInput):
    query: str = Field(min_length=1)
    service: str | None = Field(default=None, min_length=1)
    runtime: str | None = Field(default=None, min_length=1)
    framework: str | None = Field(default=None, min_length=1)
    top_k: int | None = Field(default=None, ge=1)


class ReadDocInput(_StrictToolInput):
    document_id_or_url: str = Field(min_length=1)
    section: str | None = Field(default=None, min_length=1)


class SearchRelatedQuestionsInput(_StrictToolInput):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1)


ToolInput = SearchDocsInput | ReadDocInput | SearchRelatedQuestionsInput
ToolHandler = Callable[[ToolInput], Awaitable[Any]]
ProfileUpdater = Callable[[Mapping[str, Any]], None]

_INPUT_MODELS: Mapping[AgentToolName, type[_StrictToolInput]] = MappingProxyType(
    {
        AgentToolName.SEARCH_DOCS: SearchDocsInput,
        AgentToolName.READ_DOC: ReadDocInput,
        AgentToolName.SEARCH_RELATED_QUESTIONS: SearchRelatedQuestionsInput,
    }
)

_DESCRIPTIONS: Mapping[AgentToolName, str] = MappingProxyType(
    {
        AgentToolName.SEARCH_DOCS: (
            "Search the indexed public Liara documentation for citable evidence."
        ),
        AgentToolName.READ_DOC: (
            "Read one indexed Liara documentation page or a named section of it."
        ),
        AgentToolName.SEARCH_RELATED_QUESTIONS: (
            "Search documentation-derived related questions and their attributed answers."
        ),
    }
)


def _native_definition(name: AgentToolName) -> dict[str, Any]:
    """OpenAI-compatible native function declaration for one allowed tool."""
    return {
        "type": "function",
        "function": {
            "name": name.value,
            "description": _DESCRIPTIONS[name],
            "strict": True,
            "parameters": _INPUT_MODELS[name].model_json_schema(),
        },
    }


AGENT_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = tuple(
    _native_definition(name) for name in AgentToolName
)
AGENT_TOOL_NAMES: frozenset[str] = frozenset(name.value for name in AgentToolName)


class AgentToolRegistry:
    """Validates and dispatches only the three documentation capabilities."""

    def __init__(
        self,
        handlers: Mapping[AgentToolName, ToolHandler],
        *,
        profile_updater: ProfileUpdater | None = None,
    ) -> None:
        expected = frozenset(AgentToolName)
        provided = frozenset(handlers)
        if provided != expected:
            missing = sorted(name.value for name in expected - provided)
            extra = sorted(str(name) for name in provided - expected)
            raise ValueError(f"agent tool registry mismatch; missing={missing}, extra={extra}")
        self._handlers = MappingProxyType(dict(handlers))
        self._profile_updater = profile_updater

    @property
    def definitions(self) -> tuple[dict[str, Any], ...]:
        return AGENT_TOOL_DEFINITIONS

    def set_profile(self, profile: Mapping[str, Any]) -> None:
        if self._profile_updater is not None:
            self._profile_updater(profile)

    async def execute(self, name: str, arguments: str | Mapping[str, Any]) -> Any:
        """Reject an unlisted name before considering its arguments or a handler."""
        try:
            tool_name = AgentToolName(name)
        except ValueError as err:
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail=f"agent requested non-allowlisted tool {name!r}",
            ) from err

        try:
            raw = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
            parsed = _INPUT_MODELS[tool_name].model_validate(raw)
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as err:
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail=f"invalid arguments for agent tool {tool_name.value}",
            ) from err
        return await self._handlers[tool_name](parsed)


def _page_title(metadata: Mapping[str, Any]) -> str | None:
    explicit = metadata.get("page_title")
    if explicit:
        return str(explicit)
    breadcrumbs = [str(value) for value in metadata.get("breadcrumbs") or []]
    section = metadata.get("section_title")
    if section and breadcrumbs and breadcrumbs[-1] == section:
        breadcrumbs.pop()
    return breadcrumbs[-1] if breadcrumbs else None


def _chunk_evidence(result: Any) -> dict[str, Any]:
    return {
        "evidence_id": f"chunk:{result.chunk_id}",
        "text": result.text,
        "similarity": result.similarity,
        "metadata": result.metadata,
        "images": result.images,
        "citation": {
            "url": result.citation_url,
            "page_title": _page_title(result.metadata),
            "section_title": result.metadata.get("section_title"),
            "source_commit": result.source_commit,
        },
    }


def _faq_evidence(result: Any) -> dict[str, Any]:
    return {
        "evidence_id": f"faq:{result.faq_item_id}",
        "question": result.question,
        "text": result.answer,
        "similarity": result.similarity,
        "tags": result.tags,
        "citation": {
            "url": result.citation_url,
            "page_title": result.question,
            "section_title": None,
            "source_commit": result.source_commit,
        },
    }


def build_documentation_tool_registry(
    executor: Executor,
    embeddings: FaqEmbeddingProvider,
    *,
    settings: Settings | None = None,
    telemetry: RetrievalTelemetry | None = None,
    profile: Mapping[str, Any] | None = None,
) -> AgentToolRegistry:
    """Bind the allowlist to the one shared Liara retrieval core."""
    settings = settings or get_settings()
    telemetry = telemetry or RetrievalTelemetry()
    profile_context = dict(profile or {})

    async def search_docs(arguments: ToolInput) -> list[dict[str, Any]]:
        assert isinstance(arguments, SearchDocsInput)
        explicit = {
            key: value
            for key, value in {
                "service": arguments.service,
                "runtime": arguments.runtime,
                "framework": arguments.framework,
            }.items()
            if value
        }
        requested = arguments.top_k or settings.retrieval_top_k
        results = await search_documentation(
            executor,
            arguments.query,
            embeddings,
            settings=settings,
            top_k=min(requested, settings.retrieval_top_k),
            intent=RetrievalIntent(
                profile_hints={
                    key: str(profile_context[key])
                    for key in ("service", "runtime", "framework")
                    if profile_context.get(key)
                },
                explicit_filters=explicit,
            ),
            telemetry=telemetry,
        )
        return [_chunk_evidence(result) for result in results]

    async def read_doc(arguments: ToolInput) -> list[dict[str, Any]]:
        assert isinstance(arguments, ReadDocInput)
        identifier = arguments.document_id_or_url.strip()
        url, _, url_anchor = identifier.partition("#")
        section = arguments.section or url_anchor or None
        try:
            document_id = uuid.UUID(identifier)
        except ValueError:
            document_id = None

        try:
            active_id = (
                await executor.execute(
                    select(IndexVersion.id).where(IndexVersion.is_active.is_(True))
                )
            ).scalar_one_or_none()
            if active_id is None:
                raise RescueError(
                    ErrorCode.NO_ACTIVE_INDEX,
                    detail="read_doc requested while no index version is active",
                )
            identity = (
                Document.id == document_id
                if document_id is not None
                else Document.source_url == url
            )
            section_filter = []
            if section:
                section_filter.append(
                    or_(
                        DocumentChunk.heading_anchor == section,
                        DocumentChunk.section_title == section,
                    )
                )
            rows = (
                await executor.execute(
                    select(DocumentChunk, Document.title)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(
                        DocumentChunk.index_version_id == active_id,
                        identity,
                        *section_filter,
                    )
                    .order_by(DocumentChunk.ordinal)
                    .limit(settings.retrieval_top_k)
                )
            ).all()
        except RescueError:
            raise
        except SQLAlchemyError as err:
            raise RescueError(
                ErrorCode.RETRIEVAL_FAILED,
                detail="database failed while reading an indexed document",
            ) from err
        if not rows:
            raise RescueError(
                ErrorCode.NO_RESULTS_ABOVE_THRESHOLD,
                detail="active index contains no matching document or section",
            )
        return [
            {
                "evidence_id": f"chunk:{row.DocumentChunk.id}",
                "text": row.DocumentChunk.text,
                "images": list(row.DocumentChunk.images or []),
                "metadata": {
                    "source_path": row.DocumentChunk.source_path,
                    "page_title": row.title,
                    "section_title": row.DocumentChunk.section_title,
                    "breadcrumbs": list(row.DocumentChunk.breadcrumbs or []),
                    "service": row.DocumentChunk.service,
                    "runtime": row.DocumentChunk.runtime,
                    "framework": row.DocumentChunk.framework,
                    **dict(row.DocumentChunk.extra_metadata or {}),
                },
                "citation": {
                    "url": (
                        f"{row.DocumentChunk.source_url}#{row.DocumentChunk.heading_anchor}"
                        if row.DocumentChunk.heading_anchor
                        else row.DocumentChunk.source_url
                    ),
                    "page_title": row.title,
                    "section_title": row.DocumentChunk.section_title,
                    "source_commit": row.DocumentChunk.source_commit,
                },
            }
            for row in rows
        ]

    async def search_related(arguments: ToolInput) -> list[dict[str, Any]]:
        assert isinstance(arguments, SearchRelatedQuestionsInput)
        requested = arguments.top_k or settings.faq_top_k
        results = await match_faqs(
            executor,
            arguments.query,
            embeddings,
            settings=settings,
            top_k=min(requested, settings.faq_top_k),
        )
        return [_faq_evidence(result) for result in results]

    def update_profile(updated: Mapping[str, Any]) -> None:
        profile_context.clear()
        profile_context.update(updated)

    return AgentToolRegistry(
        {
            AgentToolName.SEARCH_DOCS: search_docs,
            AgentToolName.READ_DOC: read_doc,
            AgentToolName.SEARCH_RELATED_QUESTIONS: search_related,
        },
        profile_updater=update_profile,
    )
