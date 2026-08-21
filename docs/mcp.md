# MCP server — connecting a coding agent

The Liara Docs Rescue MCP server exposes the same documentation retrieval the
web chat uses, so a user who prefers their own coding agent never has to open
the web application.

**Endpoint:** `https://liara-rescue-api.liara.run/mcp`
**Transport:** Streamable HTTP, stateless
**Authentication:** none

> **No Liara account credential is required.** This serves *public*
> documentation. Any credential this endpoint ever requires would exist to
> protect this service from abuse, never to gate access to public docs. An
> agent that asks a user for their Liara password to read documentation is
> misconfigured — see the Skill's evidence rules.

---

## Tools

| Tool | Use it for | Required argument |
|---|---|---|
| `search` | How-to and conceptual questions | `query` |
| `get_document` | Reading the full page or section a citation points at | `document_id_or_url` |
| `diagnose` | A concrete failure with an error message | `problem` |

`diagnose` also accepts `error_text`. Pass the error **verbatim**, never
paraphrased: the exact string is the highest-signal term available, and lexical
retrieval matches it literally where an embedding of a paraphrase would not.
The server keeps that literal failure in both searches, then runs a second
remediation-oriented query for prerequisites, checks, and corrective steps.
Distinct remediation passages are promoted within the same configured evidence
budget, so a definition cannot crowd every actionable result out.

Every result carries a citation — anchored `source_url`, page title, section
title, and the documentation commit it came from — plus image metadata where the
source section has one. Attach those citations to the claims they support.

### Failures name their own cause

The tools never return an empty success to mean "something went wrong". Three
of these look alike from the outside and must never be collapsed into one
message — only the second is about the documentation:

| Code | What it means | What to tell the user |
|---|---|---|
| `NO_ACTIVE_INDEX` | The service is not ready. Ingestion never ran or activation failed. | An operational failure. Do **not** present it as "no documentation found". |
| `NO_RESULTS_ABOVE_THRESHOLD` | The index is healthy and simply has no relevant evidence. | A genuine documentation gap. Say so; do not answer from memory. |
| `NO_RESULTS_FOR_FILTER` | A `service`/`runtime`/`framework` value the corpus does not use removed every candidate. | Retry without the filter. **Not** a documentation gap. |
| `RATE_LIMITED` | The per-IP request budget for this minute is spent. | Wait and retry; the error carries `retry_after`. |

### Filters are hard filters

`service`, `runtime`, and `framework` **remove** results rather than reordering
them. Pass one only when the user stated it; metadata boosting already favours
the right pages without a filter.

The index stores `runtime` as `nodejs`, `python`, `php`, `go`, `docker`,
`dotnet`, or `static` — taken from the documentation's own directory names.
Common aliases (`node`, `node.js`, `js`, `ts`, `py`, `golang`, `.net`, `c#`)
are normalized. Anything else raises `NO_RESULTS_FOR_FILTER` naming the values
that do exist, rather than reporting an empty result that reads as a
documentation gap.

---

## Host configuration

### Claude Code

```bash
claude mcp add --transport http liara-docs-rescue https://liara-rescue-api.liara.run/mcp
```

Or in `.mcp.json` at the project root, to share it with a team:

```json
{
  "mcpServers": {
    "liara-docs-rescue": {
      "type": "http",
      "url": "https://liara-rescue-api.liara.run/mcp"
    }
  }
}
```

### Cursor

`.cursor/mcp.json` for one project, or `~/.cursor/mcp.json` for every project:

```json
{
  "mcpServers": {
    "liara-docs-rescue": {
      "url": "https://liara-rescue-api.liara.run/mcp"
    }
  }
}
```

### Codex

From the CLI:

```bash
codex mcp add liara-docs-rescue --url https://liara-rescue-api.liara.run/mcp
```

Or in `~/.codex/config.toml` (the Codex app, CLI, and IDE extension share it):

```toml
[mcp_servers.liara-docs-rescue]
url = "https://liara-rescue-api.liara.run/mcp"
```

### Open WebUI

Open **Admin Settings → Integrations → Add Connection**, choose **MCP
(Streamable HTTP)**, and enter the endpoint. Native remote MCP support requires
Open WebUI 0.6.31 or newer and server connections are configured by an admin.

### Jan

Open **Settings → MCP Servers → Add MCP Server**, choose **HTTP**, enter the
endpoint, and enable the server. Start a fresh chat after changing the tool list.

### AnythingLLM

Use the MCP management screen in Agent settings, or add a streamable server to
`anythingllm_mcp_servers.json`:

```json
{
  "liara-docs-rescue": {
    "type": "streamable",
    "url": "https://liara-rescue-api.liara.run/mcp"
  }
}
```

The web UI presents these six hosts as separate expandable cards because the
configuration location and transport wording differ even though the endpoint
is identical.

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

Choose **Streamable HTTP**, enter the endpoint, and connect.

---

## Verifying the connection by hand

Everything below runs against the deployed service with no client library.

```bash
curl -sS -X POST https://liara-rescue-api.liara.run/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Expect the three tool names with complete input schemas.

```bash
curl -sS -X POST https://liara-rescue-api.liara.run/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
        "name":"search",
        "arguments":{"query":"چطور برنامه Node.js را روی لیارا دیپلوی کنم؟"}}}'
```

Expect passages whose citations resolve to `docs.liara.ir` URLs with section
anchors.

### Two things that look like server faults and are not

**`406 Not Acceptable`.** Streamable HTTP requires the client to accept *both*
content types, even though this server is configured to answer with JSON. A host
sending only `Accept: application/json` is refused. Send
`application/json, text/event-stream`.

**A `405` right after a deploy.** Liara keeps the previous release serving until
the new one is healthy, so for a few seconds the old code answers. Retry.

---

## Operational notes

- **Rate limiting** is per IP, shared with the HTTP API. A caller refused at
  `/api/v1/chat` cannot route around it through an MCP tool. `RATE_LIMITED`
  carries `retry_after` in seconds.
- **Both `/mcp` and `/mcp/`** reach the transport. Starlette's `Mount` matches
  only the trailing-slash form, and hosts are configured with the bare path far
  more often, so the exact route is registered as well.
- **Stateless** by choice: the API sits behind Liara's router with no session
  affinity, and a streamable-HTTP session pinned to one replica would break the
  moment the platform scaled past one.
- **The server runs in the API process**, sharing the index, the connection
  pool, and the rate limiter. A separate process would need its own copy of all
  three and could disagree with the first about which index version is active.
