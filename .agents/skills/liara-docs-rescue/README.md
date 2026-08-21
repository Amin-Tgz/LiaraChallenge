# Liara Docs Rescue Skill

Version: `0.3.0`

This Skill gives a coding agent Liara's official source map, documentation information architecture, MDX schema, route-selection rules, and an evidence-first troubleshooting workflow. It preserves citations and relevant images, abstains without evidence, and ends with a verification step.

The MCP server is the preferred retrieval path because it searches the indexed corpus and returns structured evidence. The downloadable `SKILL.md` is nevertheless self-contained: when MCP is unavailable, it directs the agent to the official documentation and source repository and explains how to extract the MDX safely. In either mode, the agent must not answer technical claims from memory.

## 1. Connect the MCP server

**Endpoint:** `https://liara-rescue-api.liara.run/mcp` — Streamable HTTP, no authentication.

No Liara account credential is required. This serves public documentation.

```bash
# Claude Code
claude mcp add --transport http liara-docs-rescue https://liara-rescue-api.liara.run/mcp
```

```json
// Cursor — .cursor/mcp.json (project) or ~/.cursor/mcp.json (all projects)
{
  "mcpServers": {
    "liara-docs-rescue": { "url": "https://liara-rescue-api.liara.run/mcp" }
  }
}
```

```toml
# Codex — ~/.codex/config.toml
[mcp_servers.liara-docs-rescue]
url = "https://liara-rescue-api.liara.run/mcp"
```

Full host coverage, the tool reference, and how to verify the connection by hand: [`docs/mcp.md`](../../../docs/mcp.md).

## 2. Install the Skill

The checked-in path `.agents/skills/liara-docs-rescue` is discovered automatically by Codex and Cursor when either agent runs in this repository.

For user-wide installation, copy this entire directory—not only `SKILL.md`—to the host's user Skill directory:

| Host | Project scope | User scope | Invoke |
|---|---|---|---|
| Codex | `.agents/skills/liara-docs-rescue` | `~/.agents/skills/liara-docs-rescue` | `$liara-docs-rescue` |
| Claude Code | `.claude/skills/liara-docs-rescue` | `~/.claude/skills/liara-docs-rescue` | `/liara-docs-rescue` |
| Cursor | `.agents/skills/liara-docs-rescue` | `~/.agents/skills/liara-docs-rescue` | `/liara-docs-rescue` |

Codex may need a restart if a newly copied Skill does not appear. Confirm discovery with `/skills` in Codex, `/liara-docs-rescue` in Claude Code, or the Skills view in Cursor.

References: [Codex Skill locations](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills), [Claude Code Skills](https://code.claude.com/docs/en/slash-commands), and [Cursor Agent Skills](https://cursor.com/docs/skills).

## 3. Worked example — evidence found

User request:

> گواهی SSL دامنه من روی لیارا صادر نمی‌شود. چطور عیب‌یابی کنم؟

Expected Skill behavior:

1. Preserve the symptom and identify the domains/SSL area without guessing the domain name.
2. Call `diagnose` with the problem text, passing any error message verbatim.
3. Answer in Persian using only the retrieved steps and runnable commands.
4. Cite the exact anchored sections, keep any cited screenshot URL and alt text beside the step it explains, and end with a check that proves the certificate is issued.

Verified against the deployed service on 2026-08-21. `diagnose` returned eight passages at documentation commit `dbb7430`, led by:

| Similarity | Source |
|---:|---|
| 0.507 | `docs.liara.ir/paas/domains/enable-ssl` |
| 0.435 | `docs.liara.ir/paas/domains/add-wildcard-domain#differences-between-ssl-certificates` |
| 0.430 | `docs.liara.ir/paas/domains/use-cdn` |

Reproduce it:

```bash
curl -sS -X POST https://liara-rescue-api.liara.run/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
        "name":"diagnose",
        "arguments":{"problem":"گواهی SSL دامنه من روی لیارا صادر نمی‌شود"}}}'
```

## 4. Worked example — no evidence, and why that is a success

The abstention path matters more than the happy path, because it is the one an agent is tempted to paper over.

> برنامهٔ Node.js من روی لیارا با خطای دقیق `MODULE_NOT_FOUND` بالا نمی‌آید. چطور عیب‌یابی کنم؟

Verified against the deployed service on 2026-08-21: `diagnose` returned

```text
NO_RESULTS_ABOVE_THRESHOLD: مستندات ایندکس شده‌اند، اما پاسخی مرتبط با این
سؤال پیدا نشد.
```

That is the **correct** outcome, not a failure. The Skill requires the agent to say so rather than reconstruct a plausible fix from memory. Inventing `npm ci` advice here would be exactly the behavior this Skill exists to prevent.

This example is subtler than it looks, and that is why it is the one kept. The corpus is **not** empty on this topic — it has a `ModuleNotFoundError` page for **Flask**, which retrieves at 0.638 for a query about the Node.js error. A near neighbour that a careless agent would happily mistake for a match. The right answer is still to abstain: no retrieved passage addresses Node.js `MODULE_NOT_FOUND`, and adapting Python advice to a Node.js runtime is inventing, not citing.

Distinguish it from the other empty-looking result:

- `NO_RESULTS_ABOVE_THRESHOLD` — the service works; the documentation has a gap. Tell the user that.
- `NO_ACTIVE_INDEX` — the service is broken and an operator must act. Never present this as "no documentation found".

## Filters remove results — they do not reorder them

`service`, `runtime`, and `framework` are hard filters. Pass one only when the user stated it.

The index stores `runtime` as `nodejs`, `python`, `php`, `go`, `docker`, `dotnet`, or `static`. Common aliases (`node`, `js`, `ts`, `py`, `golang`, `.net`, `c#`) are normalized; anything else returns `NO_RESULTS_FOR_FILTER`, which is **not** a documentation gap — retry without the filter.

This was a real bug found by agent verification: `runtime="node"` used to return nothing, and an agent correctly following the rules reported a documentation gap over documentation that existed.
