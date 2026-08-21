"""The MCP endpoint as a host actually reaches it.

Calling `mcp.list_tools()` in-process proves the tools are registered. It does
not prove a host can reach them: the endpoint is a *mounted sub-application*,
and Starlette does not run a mounted app's lifespan. Getting that wrong yields a
server that mounts cleanly, accepts a connection, and fails on the first tool
call — which reads as a broken tool rather than a server that never started.
These tests speak the wire protocol for that reason.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from src.core.errors import ErrorCode, RescueError
from src.main import MCP_PREFIX, create_app

PROTOCOL_VERSION = "2025-06-18"
#: Streamable HTTP requires a client to accept both, even when the server is
#: configured to answer with JSON. A host that sends only `application/json`
#: is refused, which is worth pinning because it looks like a server fault.
ACCEPT = "application/json, text/event-stream"


@asynccontextmanager
async def mcp_client() -> AsyncIterator[httpx.AsyncClient]:
    """A client bound to the real app, with the lifespan actually run.

    Deliberately a context manager used inside each test rather than a fixture.
    The MCP session manager holds an anyio task group, and pytest-asyncio
    finalizes an async-generator fixture in a different task than it set it up
    in — which makes the task group refuse to close with "attempted to exit
    cancel scope in a different task". Entering and leaving it inside the test's
    own task sidesteps that entirely.
    """
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


def _rpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


async def _post(client: httpx.AsyncClient, body: dict) -> httpx.Response:
    return await client.post(
        MCP_PREFIX,
        json=body,
        headers={"Accept": ACCEPT, "Content-Type": "application/json"},
    )


def _payload(response: httpx.Response) -> dict:
    """Read one JSON-RPC result from either response encoding."""
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise AssertionError("event stream carried no data frame")
    return response.json()


async def test_initialize_reports_the_server_identity() -> None:
    async with mcp_client() as client:
        response = await _post(
            client,
            _rpc(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "integration-test", "version": "0"},
                },
            ),
        )
    assert response.status_code == 200, response.text
    result = _payload(response)["result"]
    assert result["serverInfo"]["name"] == "liara-docs-rescue"
    # The instructions are how a host learns the evidence rules. A server that
    # returns none is one an agent will drive from its own priors.
    assert result.get("instructions")


async def test_a_host_can_list_the_tools_over_http() -> None:
    async with mcp_client() as client:
        response = await _post(client, _rpc("tools/list", {}, request_id=2))
    assert response.status_code == 200, response.text
    tools = _payload(response)["result"]["tools"]
    assert {tool["name"] for tool in tools} == {"search", "get_document", "diagnose"}
    for tool in tools:
        assert tool["inputSchema"]["properties"]


async def test_invalid_tool_input_names_the_offending_field() -> None:
    async with mcp_client() as client:
        response = await _post(
            client,
            _rpc("tools/call", {"name": "search", "arguments": {}}, request_id=3),
        )
    assert response.status_code == 200, response.text
    payload = _payload(response)
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "query" in rendered
    # Whether the SDK reports this as a protocol error or a tool result, it must
    # not read as a successful empty search.
    assert payload.get("error") or payload["result"].get("isError")


async def test_the_bare_and_trailing_slash_paths_both_reach_the_transport() -> None:
    # Hosts are configured with `/mcp` far more often than `/mcp/`, and a mount
    # alone serves only the latter. Both spellings are part of the contract.
    initialize = _rpc(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "0"},
        },
    )
    async with mcp_client() as client:
        for path in (MCP_PREFIX, f"{MCP_PREFIX}/"):
            response = await client.post(
                path,
                json=initialize,
                headers={"Accept": ACCEPT, "Content-Type": "application/json"},
            )
            assert response.status_code == 200, f"{path} -> {response.status_code}"
            assert _payload(response)["result"]["serverInfo"]["name"] == "liara-docs-rescue"


async def test_the_mcp_mount_does_not_shadow_the_api() -> None:
    # `/mcp` is in the SPA catch-all's reserved list; a regression there would
    # serve index.html to an MCP host, which fails in a deeply confusing way.
    async with mcp_client() as client:
        health = await client.get("/health/live")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


async def test_a_host_missing_the_event_stream_accept_header_is_refused_clearly() -> None:
    async with mcp_client() as client:
        response = await client.post(
            MCP_PREFIX,
            json=_rpc("tools/list", {}, request_id=4),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
    # Documented here rather than treated as a bug: the transport requires it,
    # and the 406 is what a misconfigured host will actually see.
    assert response.status_code == 406
    assert "text/event-stream" in response.text


async def test_the_mcp_surface_is_rate_limited_like_the_http_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller refused at /api/v1 must not route around it through a tool.

    Two things are asserted, and neither is "the limiter counts correctly" —
    that is `test_rate_limit.py`'s job against a real Redis. What matters *here*
    is that the MCP tool path calls the guard at all, and that a refusal reaches
    the host as the Persian user message rather than the operator detail. The
    second half is a regression test: the guard originally ran outside the
    error-conversion block, and `RATE_LIMITED: ip rate limit of 30 requests per
    minute exceeded` went to the user.

    Driving the real limiter to its ceiling from here would mean thirty-odd live
    embedding calls, and — the fixed window being one minute — would flake the
    moment those calls straddled a boundary.
    """

    async def _always_limited(**_: object) -> None:
        raise RescueError(
            ErrorCode.RATE_LIMITED,
            detail="ip rate limit of 30 requests per minute exceeded",
            context={"rate_limit_scope": "ip", "retry_after": 42},
        )

    monkeypatch.setattr("src.mcp.server.enforce_rate_limit", _always_limited)

    async with mcp_client() as client:
        response = await _post(
            client,
            _rpc(
                "tools/call",
                {"name": "search", "arguments": {"query": "لیارا"}},
                request_id=9,
            ),
        )

    assert response.status_code == 200, response.text
    rendered = json.dumps(_payload(response), ensure_ascii=False)
    assert "RATE_LIMITED" in rendered
    # The Persian message a host shows a person...
    assert "تعداد درخواست‌ها زیاد است" in rendered
    # ...and never the operator detail, which names internal thresholds.
    assert "requests per minute exceeded" not in rendered
