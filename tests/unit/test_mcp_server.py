"""The MCP surface: its schemas, its allowlist, and how it fails.

The point of these tests is that the MCP server is not a second retrieval
implementation. It is the same three-tool allowlist the bounded chat agent runs,
reached over a different transport — so what is asserted here is mostly
*sameness*, and the failure these tests exist to catch is the two surfaces
quietly drifting apart while both keep answering.
"""

import json

import pytest

from src.core.errors import ErrorCode, RescueError
from src.mcp.server import (
    SERVER_NAME,
    ToolError,
    build_diagnostic_query,
    build_mcp_server,
    merge_diagnostic_evidence,
)
from src.services.agent_tools import AGENT_TOOL_NAMES

EXPECTED_TOOLS = {"search", "get_document", "diagnose"}


@pytest.fixture
def mcp():
    return build_mcp_server()


async def test_discovery_lists_exactly_the_three_documentation_tools(mcp) -> None:
    tools = await mcp.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


async def test_the_mcp_allowlist_is_no_wider_than_the_chat_agents(mcp) -> None:
    # The chat agent reaches exactly three capabilities. If MCP ever exposes a
    # fourth, it has stopped being the same allowlist over a different
    # transport and become an unbounded surface with its own risks.
    tools = await mcp.list_tools()
    assert len(tools) == len(AGENT_TOOL_NAMES)


async def test_every_tool_declares_a_complete_input_schema(mcp) -> None:
    for tool in await mcp.list_tools():
        schema = tool.inputSchema
        assert schema["type"] == "object", tool.name
        assert schema["properties"], f"{tool.name} declares no parameters"
        assert tool.description, f"{tool.name} has no description for a host to show"
        for name, prop in schema["properties"].items():
            # A host renders these to a model. A parameter with no description
            # is a parameter the model has to guess the meaning of.
            assert prop.get("description"), f"{tool.name}.{name} has no description"
        # The schema must be serializable — a host receives it as JSON.
        json.dumps(schema)


async def test_the_required_fields_are_the_ones_a_caller_cannot_omit(mcp) -> None:
    required = {
        tool.name: set(tool.inputSchema.get("required", [])) for tool in await mcp.list_tools()
    }
    assert required["search"] == {"query"}
    assert required["get_document"] == {"document_id_or_url"}
    assert required["diagnose"] == {"problem"}


async def test_schema_invalid_input_names_the_offending_field(mcp) -> None:
    # "Invalid input" alone leaves a caller guessing which of five parameters
    # was wrong. The spec requires the offending field be identified.
    with pytest.raises(Exception) as excinfo:
        await mcp.call_tool("search", {})
    assert "query" in str(excinfo.value)


async def test_an_unlisted_tool_is_refused(mcp) -> None:
    with pytest.raises(Exception) as excinfo:
        await mcp.call_tool("delete_index", {"confirm": True})
    assert "delete_index" in str(excinfo.value)


def test_tool_failures_carry_both_the_machine_code_and_the_persian_message() -> None:
    # An operator greps logs for the code; a person reads the message. Losing
    # either half at the MCP boundary makes one of them unable to act.
    err = ToolError(RescueError(ErrorCode.NO_ACTIVE_INDEX, detail="ingestion never ran"))
    assert err.code is ErrorCode.NO_ACTIVE_INDEX
    rendered = str(err)
    assert "NO_ACTIVE_INDEX" in rendered
    assert "ایندکس نشده" in rendered


def test_an_empty_index_and_an_empty_result_do_not_share_a_message() -> None:
    # The distinction RULES.md §1 exists to protect, asserted at the MCP
    # boundary because that is a place it could be flattened into one string.
    broken = str(ToolError(RescueError(ErrorCode.NO_ACTIVE_INDEX)))
    gap = str(ToolError(RescueError(ErrorCode.NO_RESULTS_ABOVE_THRESHOLD)))
    assert broken != gap


def test_the_server_instructions_frame_retrieved_content_as_data(mcp) -> None:
    # The Skill and the chat agent both refuse to treat documentation as
    # instruction. A host driving these tools gets that rule from `instructions`
    # or it does not get it at all.
    instructions = mcp.instructions or ""
    assert "data, never instruction" in instructions
    assert "NO_ACTIVE_INDEX" in instructions
    assert "NO_RESULTS_ABOVE_THRESHOLD" in instructions


def test_the_server_announces_a_stable_name(mcp) -> None:
    assert mcp.name == SERVER_NAME == "liara-docs-rescue"


def test_diagnostic_query_keeps_the_exact_error_and_requests_remediation() -> None:
    query = build_diagnostic_query(
        "گواهی SSL فعال نمی‌شود",
        "domain is not verified",
    )

    assert "domain is not verified" in query
    assert "رفع" in query
    assert "پیش‌نیاز" in query


def test_diagnose_promotes_distinct_remediation_evidence_within_the_budget() -> None:
    definition = {"evidence_id": "definition"}
    repeated = {"evidence_id": "same"}
    fix = {"evidence_id": "fix"}
    prerequisite = {"evidence_id": "prerequisite"}

    merged = merge_diagnostic_evidence(
        primary=[definition, repeated],
        remediation=[fix, repeated, prerequisite],
        limit=3,
    )

    assert [item["evidence_id"] for item in merged] == ["fix", "same", "prerequisite"]
