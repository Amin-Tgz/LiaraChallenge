# Liara Docs Rescue Skill

Version: `0.1.0`

This Skill teaches a coding agent to retrieve Liara documentation before answering, preserve citations and relevant images, abstain without evidence, and give the user a verification step.

## Install

The checked-in path `.agents/skills/liara-docs-rescue` is discovered automatically by Codex and Cursor when either agent runs in this repository.

For user-wide installation, copy this entire directory—not only `SKILL.md`—to the host's user Skill directory:

| Host | Project scope | User scope | Invoke |
|---|---|---|---|
| Codex | `.agents/skills/liara-docs-rescue` | `~/.agents/skills/liara-docs-rescue` | `$liara-docs-rescue` |
| Claude Code | `.claude/skills/liara-docs-rescue` | `~/.claude/skills/liara-docs-rescue` | `/liara-docs-rescue` |
| Cursor | `.agents/skills/liara-docs-rescue` | `~/.agents/skills/liara-docs-rescue` | `/liara-docs-rescue` |

Codex may need a restart if a newly copied Skill does not appear. Confirm discovery with `/skills` in Codex, `/liara-docs-rescue` in Claude Code, or the Skills view in Cursor.

The host must also have the Liara Docs Rescue MCP service connected. Public Liara documentation does not require a Liara account credential; any MCP credential protects only this rescue service. Copy-ready MCP host configuration will be added with OpenSpec task 15.4 after the server endpoint and transport are implemented.

References: [Codex Skill locations](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills), [Claude Code Skills](https://code.claude.com/docs/en/slash-commands), and [Cursor Agent Skills](https://cursor.com/docs/skills).

## Worked example

User request:

> برنامهٔ Node.js من روی لیارا با خطای دقیق `MODULE_NOT_FOUND` بالا نمی‌آید. چطور عیب‌یابی کنم؟

Expected Skill behavior:

1. Preserve `MODULE_NOT_FOUND` and identify the likely PaaS/Node.js context without guessing the missing module.
2. Invoke the MCP diagnose capability with the original question and known context.
3. If needed, search the exact error and read the strongest returned document section.
4. Answer in Persian using only retrieved steps and runnable commands.
5. Cite the exact anchored Liara documentation sections, retain any cited screenshot URL and alt text, and end with a check that proves the application starts successfully.
6. If retrieval returns `NO_RESULTS_ABOVE_THRESHOLD`, state that the indexed docs have no relevant evidence. If it returns `NO_ACTIVE_INDEX`, report the service readiness failure instead. In neither case invent a fix.

Runtime verification of this example requires the deployed MCP endpoint and is intentionally pending OpenSpec tasks 12.2, 12.3, and 15.1–15.4.
