# Liara Docs Rescue Skill

Version: `0.2.0`

This Skill teaches a coding agent to retrieve Liara documentation before answering, preserve citations and relevant images, abstain without evidence, and give the user a verification step.

It is useless on its own. The Skill is the *workflow*; the evidence comes from the Liara Docs Rescue MCP server, and an agent with the Skill but no MCP connection has been told to retrieve from something that is not there. Connect the MCP server first.

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

That is the **correct** outcome, not a failure. The indexed documentation has no page about this error, and the Skill requires the agent to say so rather than reconstruct a plausible fix from memory. Inventing `npm ci` advice here would be exactly the behavior this Skill exists to prevent.

Distinguish it from the other empty-looking result:

- `NO_RESULTS_ABOVE_THRESHOLD` — the service works; the documentation has a gap. Tell the user that.
- `NO_ACTIVE_INDEX` — the service is broken and an operator must act. Never present this as "no documentation found".

## Known limitation

`diagnose` also returns `related_questions`, drawn from documentation-derived FAQ entries. Against the current deployment that list is **empty**: FAQ generation has not yet been run over the production index. The documentation evidence is unaffected — `related_questions` is a supplement, and the tool returns evidence without it.
