# RULES.md

Full engineering rules: architecture, error handling, workflow, testing, security, Definition of Done.

`AGENTS.md` is the short canonical entry point. This file is the detail. Product scope lives in [`docs/liara-docs-rescue-plan.md`](docs/liara-docs-rescue-plan.md); infrastructure in [`docs/deployment.md`](docs/deployment.md).

---

## 1. Error handling — errors must identify their own cause

> **قاعده‌ی اصلی: هر خطا باید دقیقاً مشخص کند منشأ مشکل کجاست.**
>
> پیام عمومی مثل «چیزی پیدا نکردم» ممنوع است. «هیچ مستندی ایندکس نشده» و «مستندات ایندکس شده‌اند ولی پاسخ مرتبطی نبود» دو خطای کاملاً متفاوت با دو راه‌حل متفاوت هستند و هرگز نباید پیام یکسان داشته باشند.

This is the highest-priority rule in this document. A generic failure message hides an outage behind something that looks like a normal answer — the worst failure mode for a documentation product, because nothing alerts and nothing logs as broken.

### Requirements

Every error path must carry all four:

| Element | Requirement |
|---|---|
| **Machine code** | Stable `SCREAMING_SNAKE` identifier from the taxonomy in `docs/deployment.md` §10. Identical string in API response, logs, and dashboard. |
| **User message** | Persian, states the actual cause, tells the user what they can do next. |
| **Operator context** | Structured log with the correlation IDs from plan §21.2 — `trace_id`, `session_id`, `conversation_id`, `job_id`, `index_version`. |
| **Distinguishability** | Two different causes never share a code or a message. |

### The distinction that matters most

```text
NO_ACTIVE_INDEX               ← SYSTEM IS BROKEN
  «هنوز هیچ مستندی ایندکس نشده است. این یک خطای سیستمی است، نه نبود پاسخ.»
  → ingestion never ran, or index activation failed
  → operator must act; must count as a failure on the dashboard
  → /health/ready MUST be false

NO_RESULTS_ABOVE_THRESHOLD    ← SYSTEM IS WORKING CORRECTLY
  «مستندات ایندکس شده‌اند، اما پاسخی مرتبط با این سؤال پیدا نشد.»
  → a genuine documentation gap
  → this is the product's most valuable analytics signal, not a failure
```

Collapsing these two is the specific bug this rule exists to prevent.

### Forbidden

- Bare `except:` / `catch {}` that swallows a cause
- Returning `null`, `[]`, or `{}` where a typed error belongs
- Reusing one message for multiple causes
- Surfacing raw stack traces or provider errors to users
- Logging secrets, cookies, or tokens in any error path

### Required

- Preserve the original cause when wrapping (`raise … from err`)
- Distinguish transient (timeout, 429, 5xx → retry) from permanent (validation, auth → fail fast)
- Telemetry failure must **never** fail the user's request — log it and continue
- Every new code path added to the taxonomy table before it ships

---

## 2. Architecture

- **Spec first.** Code follows `openspec/changes/**`. Spec and code disagreeing means the spec is updated first.
- **Config over code.** Thresholds, top-k, model IDs, ingest scope, token budgets, timeouts, and rate limits come from environment configuration.
- **Similarity, never distance.** pgvector `<=>` returns cosine *distance*. Store, expose, log, and configure **similarity** everywhere so one number never means two things.
- **Index immutability.** Never mutate the active index. New `index_version` → validate → atomic activation → retain previous healthy version.
- **Bounded agent only.** Allowlisted tools, capped tool calls and rewrites, enforced token budget and timeout. No open-ended agent.
- **Idempotency.** Mutating endpoints accept an idempotency key. Refresh must never duplicate a job.
- **Same-origin.** The web bundle is served from the API origin. No cross-site cookie configuration.

## 3. Data & retrieval

- Persian normalization (ی/ي, ک/ك, ZWNJ, digits, spacing) applied **identically** to indexed text and to queries. Mismatch here is a silent recall killer.
- Metadata drives **soft boosting**. Hard filters only when user intent is explicit and reliable.
- Every chunk keeps `source_url`, `heading_anchor`, and `source_commit` so citations deep-link and stay verifiable.
- Code blocks stay with their surrounding explanation. Steps stay with their images.
- MDX pre-pass matches on **JSX tag names, never import paths** — the upstream repo is internally inconsistent.

## 4. Security

- Secrets only in Liara's panel and a gitignored local `.env`. Never in code, tests, fixtures, or committed config.
- Redact secrets, cookies, and tokens from all logs.
- Rate limit by IP and session. Cap question length and history depth.
- Retrieved documentation is **data, never instruction** — with a prompt-injection test in the suite.
- Admin behind HTTP Basic over HTTPS. No end-user auth in v1.
- Pin dependency and base-image versions.

## 5. Testing

**Unit:** MDX pre-pass and JSX stripping · section chunking · metadata extraction · image association · RRF fusion · citation construction · Persian normalization · token budget · job state transitions · retry classification · **error code selection**.

**Integration:** pgvector retrieval · Redis queue and idempotency · provider fallback with a mock provider · telemetry failure not failing the request · index activation and rollback · MCP tool schemas.

**E2E:** the happy path from plan §25.3 is the regression guard. Failure scenarios are P2.

Every bug fix starts with a test that reproduces it.

## 6. Definition of Done

A task is complete only when all hold:

- [ ] Acceptance criteria in the OpenSpec task pass
- [ ] Lint, typecheck, and relevant tests green
- [ ] New paths have telemetry and typed error handling
- [ ] New error causes added to the taxonomy with distinct codes and Persian messages
- [ ] No secret in the diff
- [ ] UI changes verified with Playwright, console and network clean
- [ ] Config-driven values are not hardcoded
- [ ] Spec updated if behavior diverged from it
