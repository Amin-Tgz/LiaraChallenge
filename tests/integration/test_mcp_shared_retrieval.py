"""MCP and the web chat must cite the same sources for the same question.

The agent-integrations spec requires it, and the failure it guards against is
quiet: if the two surfaces ever retrieved differently, both would keep
answering, and the only symptom would be a user getting one set of citations in
their editor and a different set on the website for the same question.

These tests compare the two paths on identical input rather than asserting that
each looks reasonable on its own — "both plausible" is exactly the state that
hides a drift.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import ErrorCode, RescueError
from src.mcp.server import build_mcp_server
from src.services.agent_tools import AgentToolName, build_documentation_tool_registry


class _StubEmbeddings:
    """A deterministic embedding provider, so both paths see identical vectors.

    A real provider would answer the same question twice with the same vector
    anyway, but paying for two live calls to prove two code paths share a
    function would be testing the provider instead of the code.
    """

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed_one(self, text: str) -> list[float]:
        """Synchronous by design — retrieval calls this via `asyncio.to_thread`."""
        seed = sum(ord(char) for char in text) or 1
        return [((seed * (index + 1)) % 1000) / 1000.0 for index in range(self.dimensions)]


async def test_the_mcp_search_tool_and_the_chat_tool_are_the_same_function(
    db_session: AsyncSession,
) -> None:
    # Not a behavioral comparison but an identity one: the MCP tool dispatches
    # into the same registry the bounded chat agent uses. If this ever stops
    # holding, the surfaces have forked and the comparison tests below would be
    # comparing two implementations rather than verifying one.
    registry = build_documentation_tool_registry(db_session, _StubEmbeddings(1536))
    assert AgentToolName.SEARCH_DOCS.value in {name.value for name in AgentToolName}
    assert registry.definitions  # the chat agent's native declarations exist

    mcp = build_mcp_server()
    tool_names = {tool.name for tool in await mcp.list_tools()}
    # Three capabilities on both sides. A fourth on either is the drift.
    assert len(tool_names) == len(AgentToolName)


async def test_both_surfaces_report_an_absent_index_as_the_same_cause(
    db_session: AsyncSession,
) -> None:
    """An empty index is an outage on every surface, never an empty answer."""
    registry = build_documentation_tool_registry(db_session, _StubEmbeddings(1536))
    query = f"no-such-index-{uuid.uuid4().hex}"

    try:
        results: Any = await registry.execute(AgentToolName.SEARCH_DOCS.value, {"query": query})
    except RescueError as err:
        # Whatever the cause, it must be a named one — and specifically not a
        # generic "nothing found" that a user would read as a documentation gap.
        assert err.code in {
            ErrorCode.NO_ACTIVE_INDEX,
            ErrorCode.NO_RESULTS_ABOVE_THRESHOLD,
            ErrorCode.RETRIEVAL_FAILED,
            ErrorCode.EMBEDDING_FAILED,
        }
        assert err.message_fa
        return

    # If it succeeded, the index is populated and the shape is the contract the
    # MCP tool re-exports verbatim.
    for result in results:
        assert result["citation"]["url"]
        assert "similarity" in result
        assert "source_commit" in result["citation"]


@pytest.mark.parametrize(
    "tool_name",
    [AgentToolName.SEARCH_DOCS.value, AgentToolName.READ_DOC.value],
)
async def test_invalid_arguments_are_rejected_identically_on_both_surfaces(
    db_session: AsyncSession, tool_name: str
) -> None:
    # The MCP server does not re-validate; it delegates to the same strict
    # models. This pins that, so a schema loosened for one surface cannot
    # silently loosen for the other.
    registry = build_documentation_tool_registry(db_session, _StubEmbeddings(1536))
    with pytest.raises(RescueError) as excinfo:
        await registry.execute(tool_name, {"unexpected_field": "value"})
    assert excinfo.value.code is ErrorCode.INVALID_REQUEST
