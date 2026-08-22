# Liara Assistant

![Startcooch Vibe Coding Hackathon](docs/images/hackathon.jpg)

**Built for the Startcooch «Vibe Coding» hackathon** (هکاتون وایب کدینگ استارکوچ,
28–30 Mordad), for which Liara is one of the sponsoring platforms. The judging
criteria and what this project does about each of them are in
[Judging criteria](#judging-criteria) at the end.

**دستیار لیارا** — a system for people who are stuck in Liara's
documentation and are not getting unstuck by reading more of it.

The premise is narrow and worth stating plainly: when someone cannot find an
answer, there are two completely different reasons, and a search box treats them
identically. Either the documentation covers their problem and they could not
find the page, or it does not cover their problem at all. The first is a
retrieval failure. The second is a documentation gap, and it is the single most
valuable thing this system can learn. Every design decision below follows from
refusing to collapse those two into "no results found".

---

## What it does

The front page is the conversation. A stuck user writes their question in full —
the error message, what they tried, what they expected — and everything happens
on that one screen:

1. **Related questions.** A semantic search over FAQ entries generated from the
   real documentation, shown inline. Deliberately labelled *related questions*,
   not *answers*: they are matched by similarity, and calling them answers would
   promise more than the match justifies. No answer-generation model runs on
   this path, so it is fast and cheap.
2. **A judgement.** The user says whether that helped, and nothing is generated
   until they say it did not. "It did not" is recorded with the question and the
   pages implicated — that is the documentation-gap signal, stored rather than
   merely counted.
3. **Grounded chat.** A bounded agent that answers from retrieved documentation
   only, in the same place. Every technical claim carries a citation that
   deep-links to the section it came from. When the evidence is insufficient it
   abstains and says so rather than guessing. While it works, it shows the real
   search steps it is taking — the tool, the query, how many passages came back
   and how close the best one was.
4. **A verdict on the answer.** 👍/👎 with a reason, joined server-side to the
   pages that answer cited. That join is what turns a complaint into "this page
   keeps producing bad answers", which is the only actionable form of it.

Two further ways in live in the sidebar, for people who would rather stay in
their editor: an installable **Skill** for a coding agent, and an **MCP server**
exposing documentation search, page reading, and diagnosis as tools.

A conversation has no turn limit. Turns that fall outside the replayed window
are summarized server-side, so cost stays bounded without the conversation ever
being cut off.

`/demo` is a stand-in Liara documentation page carrying the rescue widget, to
show where this belongs: not on its own site, but in the corner of the page
somebody is already stuck on. It reconstructs the shape of `docs.liara.ir` —
right-hand rail, centred command-palette search, gradient welcome card,
quick-start and product grids — and says plainly, in a banner that cannot be
dismissed, that it is a reconstruction and not the real documentation.
`/admin` is the operator console — feedback and metrics — behind the existing
HTTP Basic guard.

---

## The rules that shape the code

These are not style preferences. Each one exists because its absence produces a
specific, known failure.

**Every error names its own cause.** A generic "nothing found" is forbidden.
`NO_ACTIVE_INDEX` means ingestion never ran and the system is broken;
`NO_RESULTS_ABOVE_THRESHOLD` means the system worked and found a real gap. They
have nothing in common, so they never share a code or a message. Collapsing
them hides an outage behind something that looks like a normal answer — nothing
alerts, and nothing logs as broken.

**No fabricated answers.** A technical claim without retrieved evidence behind
it is a bug, not a stylistic lapse. Insufficient evidence means abstain.

**Retrieved documentation is data, never instruction.** Every passage and tool
result is untrusted input. There is a prompt-injection fixture in the test suite
that fails if that stops being true.

**Similarity, never distance.** pgvector's `<=>` returns cosine *distance*.
Everything stored, logged, configured, and returned is *similarity*, so one
number never means two things depending on where you read it.

**Config over code.** Thresholds, top-k, model ids, budgets, and timeouts come
from environment configuration. Nothing in `.env.example` is hardcoded elsewhere.

**Persian is the product language.** The UI is RTL; code blocks are LTR and
bidi-isolated, because a shell command reordered by the bidi algorithm is a
command that does not run.

Full detail lives in [`RULES.md`](RULES.md) and [`AGENTS.md`](AGENTS.md).

---

## Architecture

```text
                    ┌──────────────────────────────┐
  browser ──────────│  liara-rescue-api  (FastAPI) │
   (SPA, same       │  • serves the built SPA      │
    origin)         │  • /api/v1/*  •  /health/*   │
                    │  • SSE relay  •  /metrics    │
                    └───────┬───────────────┬──────┘
                            │               │
                  ┌─────────▼──────┐  ┌─────▼─────────────┐
                  │ PostgreSQL     │  │ Redis             │
                  │ + pgvector     │  │ queue · streams   │
                  │ vector(1536)   │  │ rate limits       │
                  └─────────▲──────┘  └─────▲─────────────┘
                            │               │
                    ┌───────┴───────────────┴──────┐
                    │  liara-rescue-worker         │
                    │  bounded agent · ingestion   │
                    └───────────────┬──────────────┘
                                    │
                    ┌───────────────▼──────────────┐
                    │  liara-rescue-gateway        │
                    │  Portkey (own container)     │
                    └───────────────┬──────────────┘
                                    │
                         AvalAI (OpenAI-compatible)
                    gemini-3.7-flash · text-embedding-3-large
```

**Generation never happens inside a request.** The API persists the question and
its job and returns immediately; a worker answers it and appends the result to a
per-job Redis Stream; the browser follows an SSE endpoint that tails that
stream. This is what makes a reload during generation restore state instead of
starting a second answer.

Three invariants hold that together:

- **The job row is written before it is enqueued.** A crash between the two
  leaves a row an operator can see and a reaper can retry. Enqueueing first
  would lose the question outright.
- **A worker holds a lease it refreshes while working.** A worker that is killed
  runs no cleanup — its lease simply stops being renewed, and the next worker to
  start reclaims any non-terminal job that has no lease and no queue entry.
- **Delivered content lives in the stream, not the connection.** The stream's
  entry ids are the offsets a client resumes from, so `Last-Event-ID` continues
  a dropped connection rather than restarting it.

The relay carries *validated answer text*, not raw model tokens. The agent's
final turn is structured JSON whose citations must be resolved before anything
is shown; forwarding raw tokens would put uncited text on screen and stream JSON
syntax instead of prose.

### Retrieval

Hybrid: dense pgvector similarity fused with lexical `tsvector` search via
Reciprocal Rank Fusion, filtered to the active index version. Metadata drives
*soft boosting*; hard filters apply only when the user's intent is explicit.

Embeddings are **1536-dimensional**, not the model's native 3072. pgvector caps
HNSW indexes at 2,000 dimensions, so 3072 is unindexable and every query would
degrade to a sequential scan.

### The MDX gotcha

The upstream corpus (`github.com/liara-cloud/docs`) is a Next.js site whose
section headings are **not Markdown** — they are `<Section id="…" title="…" />`
JSX components. A Markdown-only parser produces one undifferentiated blob per
file and retrieval collapses silently, which is the worst kind of failure
because nothing errors. A pre-pass converts the JSX first, matching on **tag
names, never import paths**, because the upstream repo is internally
inconsistent about how it imports them. See `docs/deployment.md` §7.

### Index immutability

The active index is never mutated. Ingestion builds a new `index_version`,
validates it, and activates it atomically, retaining the previous healthy
version so rollback needs no re-ingestion.

---

## Running it locally

Requirements: Docker Desktop, Node 22, and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env      # then fill in the credentials — see below
docker compose up -d      # Postgres, Redis, gateway, API, worker
```

`.env` is gitignored and must never contain a real credential in a commit. The
values you need to supply yourself:

| Variable | What it is |
|---|---|
| `LLM_API_KEY` | AvalAI key for chat and FAQ generation |
| `EMBEDDING_API_KEY` | AvalAI key for embeddings |
| `PORTKEY_FALLBACK_*` | Secondary OpenAI-compatible provider |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | HTTP Basic for the admin console |
| `OPIK_API_KEY` / `OPIK_WORKSPACE` | LLM tracing (optional) |
| `EVAL_JUDGE_MODEL` | Must differ from `LLM_MODEL` |

Then apply migrations and build the corpus:

```bash
docker compose exec api alembic upgrade head
docker compose exec api python scripts/ingest.py         # ~1,140 docs
docker compose exec api python scripts/generate_faq.py   # FAQ from the corpus
```

`/health/ready` reports each dependency separately and is only `true` once an
active index exists — it will not claim readiness with an empty corpus.

```bash
curl localhost:8000/health/ready
```

### Frontend

The SPA is served from the API origin in every environment, so there is no CORS
and no cross-site cookie configuration. For hot reload during development:

```bash
cd web && npm ci && npm run dev    # proxies /api and /health to :8000
```

---

## Verification

```bash
# Backend
uv sync --frozen
uv run ruff check . && uv run ruff format --check . && uv run pytest

# Frontend
cd web && npm ci && npm run lint && npm run typecheck && npm run test && npm run build
```

Integration tests need a real Postgres with pgvector and a real Redis; they
**skip** rather than fail when neither is reachable, so the unit suite still
runs on a bare checkout. They also run against their own Redis logical database,
so a locally running worker cannot pick up a test's job and answer it for real.

---

## Configuration

Every threshold and budget is an environment variable; `.env.example` is the
complete list. The ones most worth understanding:

| Variable | Default | Why it is what it is |
|---|---|---|
| `EMBEDDING_DIMENSIONS` | `1536` | pgvector's HNSW ceiling is 2,000. Validated at startup. |
| `RETRIEVAL_SIMILARITY_THRESHOLD` | `0.2125` | Below this, results are suppressed and the gap is recorded. Relaxed 15% from 0.25 after live use. |
| `FAQ_SIMILARITY_THRESHOLD` | `0.34` | Admin-editable at runtime. Relaxed 15% from 0.4: real questions phrased in a user's own words were sitting just under the old bar. |
| `FAQ_SHORT_QUERY_SIMILARITY_THRESHOLD` | `0.51` | Greetings and other tiny queries must clear a stronger relevance bar. Same 15% relaxation, from 0.6. |
| `FAQ_ITEMS_PER_DOCUMENT` | `15` | Upper bound for useful candidates; every accepted answer must be complete, precise, and sized to its evidence. |
| `FAQ_MAX_OUTPUT_TOKENS` | `12288` | Generation headroom, not a target length; answers must not be padded or fabricated. |
| `RETRIEVAL_DUPLICATE_THRESHOLD` | `0.9` | Near-identical passages consume one evidence slot. |
| `AGENT_TOKEN_BUDGET` | `32000` | Must hold one retrieval round (`RETRIEVAL_TOP_K` × `CHUNK_MAX_TOKENS` ≈ 9.6k) plus the answer. At the previous 8000, every well-retrieved question terminated as `AGENT_LIMIT_REACHED` before it could answer. |
| `AGENT_MAX_TOOL_CALLS` | `3` | Enforced in code, not requested in the prompt. |
| `MAX_HISTORY_TURNS` | `3` | How many turns are replayed verbatim. Older ones are summarized, not dropped. |
| `CONVERSATION_SUMMARY_TRIGGER_TURNS` | `3` | Past this, turns outside the window are folded into a running summary. Invisible to the user. |
| `MAX_CONVERSATION_TURNS` | `40` | An abuse ceiling, not a product rule. A normal conversation never reaches it. |
| `JOB_MAX_ATTEMPTS` | `3` | Retries are bounded; exhausted attempts reach `failed`, never loop. |
| `JOB_LEASE_SECONDS` | `90` | How long a dead worker's job waits before reclamation. |

Retry classification comes from the error taxonomy, not from call sites: a
timeout or an unavailable provider is transient and retries; a validation or
auth failure is permanent and fails fast. Retrying the latter would burn the
budget re-earning the same rejection.

---

## Deployment

Production runs the same services on Liara, under a team account, on the
`liara-challenge` private network:

| Service | Role |
|---|---|
| `liara-rescue-api` | FastAPI + the built SPA (`docker/Dockerfile.prod`) |
| `liara-rescue-worker` | Job consumer and ingestion |
| `liara-rescue-gateway` | Portkey gateway container |
| `liaradb` | PostgreSQL + pgvector |
| `liara-rescue-redis` | Queue, streams, rate limits |
| `liara-rescue-prometheus` · `-grafana` · `-loki` · `-alloy` | Metrics, dashboards, logs |

Secrets live in Liara's panel — never in code, tests, fixtures, or committed
config. `.liaraignore` keeps `.env`, `secrets/`, and local state out of the
deploy bundle; Liara does **not** read your local `.env`, so every production
value must be set explicitly on the app.

Deploy the API before the Worker. The production API entrypoint runs
`alembic upgrade head` before Uvicorn starts and exits on migration failure;
the Worker deliberately does not run migrations, avoiding an Alembic race.

```bash
liara deploy --app liara-rescue-api --team-id <team> \
  --path . --dockerfile docker/Dockerfile.prod --port 8000
```

Inter-service traffic uses private hostnames (`http://liara-rescue-gateway:8787`,
`http://liara-rescue-alloy:4318/v1/logs`), so the monitoring stack does not need
public exposure.

### Observability

Prometheus scrapes `/metrics`; Grafana holds the dashboards; Alloy receives OTLP
logs and forwards them to Loki; Opik traces retrieval and generation spans.
**Telemetry failure never fails a user's request** — it is logged and dropped.

Loki runs with `deletion_mode: disabled`. `retention_enabled: false` alone was
not enough: deletion is separately enabled by default, so the compactor still
tried to open a delete-request store on the Liara persistent disk and timed out,
aborting startup.

---

## Repository layout

```text
src/
  core/         config, structured logging, the error taxonomy
  api/v1/       routers, registered centrally in routes.py
  db/models/    async SQLAlchemy 2.x models
  services/     ingestion, retrieval, faq, agent, jobs, job_runner, summarization
  mcp/          MCP tools over the shared retrieval core
  worker.py     queue consumer
alembic/        migrations — every schema change, no create_all
web/            React + TypeScript + Vite; built bundle served by the API
monitoring/     Prometheus, Grafana, Loki, Alloy images and config
docs/           deployment decisions and the product plan
openspec/       change proposals, delta specs, task lists
```

## Where the specifications live

Code follows these. When code and spec disagree, the spec is updated first.

| Document | Owns |
|---|---|
| `openspec/changes/**` | The active change: design, delta specs, acceptance criteria |
| `docs/deployment.md` | Infrastructure, models, config, MDX pre-pass, error taxonomy |
| `docs/liara-docs-rescue-plan.md` | Product scope, UX, evaluation, Definition of Done |

Precedence: the active change beats `deployment.md` on specifics,
`deployment.md` beats the plan on infrastructure, and the plan beats
`deployment.md` on product scope.

---

## Judging criteria

What follows maps each hackathon criterion to the specific thing in this
repository that addresses it, with a file to look at.

**Rows marked *planned* are not built yet.** They carry the OpenSpec task that
owns them. A table that claims work nobody did is worth less than a table that
says where the edges are, so the edges are stated.

### 1. Answer quality and correctness — 80 points

| Criterion | What addresses it | Where |
|---|---|---|
| Correct and relevant answers | Hybrid retrieval — dense pgvector + lexical, fused with RRF, metadata-boosted — over chunks cut at real `<Section>` boundaries rather than by character count | `src/services/retrieval.py`, `src/services/ingestion/mdx.py` |
| Complete, usable answers | FAQ generation requires numbered steps, verbatim commands and config values, prerequisites, limits, and how to verify success; one-sentence answers are refused for "how" questions | `src/services/faq.py` `SYSTEM_PROMPT` |
| Finding the right information | Three tools the agent can choose between — search, read a specific page, diagnose a failure — plus query rewriting within a bounded budget | `src/services/agent_tools.py` |
| Fewer wrong or invented answers | Every technical claim must cite a retrieved evidence id; the answer is validated against the evidence set before it is persisted, and citation-less answers are marked abstentions | `src/services/agent.py` `_final_result` |
| Citing sources | Citations deep-link to the page *and section* that produced them, with the corpus commit they came from | `web/src/components/Citations.tsx`, `src/services/retrieval.py` |
| Simple and complex questions alike | Simple ones are answered by the FAQ fast path with no model call at all; complex ones go to the bounded agent. Short queries clear a stricter relevance bar so "سلام" matches nothing | `src/services/faq.py` `match_faqs` |

The system abstains rather than guessing. `NO_ACTIVE_INDEX`,
`NO_RESULTS_ABOVE_THRESHOLD`, `NO_RESULTS_FOR_FILTER`, and `NO_EVIDENCE` are
four different failures with four different messages — collapsing them into
"nothing found" is what hides an outage behind something that looks normal.

*Planned:* the golden-set evaluation harness with Recall@k, citation
correctness, and an LLM judge distinct from the model under test — tasks 16.1–16.5.

### 2. UI and user experience — 55 points

| Criterion | What addresses it | Where |
|---|---|---|
| Design quality and ease of use | One chat surface. Ask, judge what the documentation already offers, continue into the assistant — no page changes in between | `web/src/views/LandingView.tsx` |
| Conversation experience | Streamed answers over SSE; the live trace shows the real search steps, the actual query, result counts, and the best similarity — no simulated progress | `web/src/components/ThinkingTrace.tsx` |
| Code, links, and technical detail | Persian RTL body with LTR-isolated code blocks and inline code, syntax highlighting, per-block copy, and cited images beside the step they illustrate | `web/src/components/Markdown.tsx`, `Citations.tsx` |
| Continuing a conversation | No turn limit. Older turns are summarized server-side, and a reload mid-answer restores the transcript and rejoins the running job instead of starting a second one | `src/services/summarization.py`, `web/src/views/ChatView.tsx` |
| Responsive | Fixed sidebar on desktop, focus-managed drawer on mobile, safe-area-aware composer; verified at 375px and 1440px in both themes | `web/src/styles.css` |
| Asking the first question | On the empty first screen the composer sits in the middle of the page at full size, and drops to the foot of the transcript once a question is in flight. It grows with what is typed and stops at three lines, after which the earlier lines scroll inside it rather than pushing the page around | `web/src/views/LandingView.tsx`, `web/src/autogrow.ts` |
| Operator console legibility | Long questions, index ids, and URLs wrap inside their metric card instead of overflowing it, and a cited page is a link to that page rather than inert text | `web/src/views/AdminView.tsx` |
| UX detail | Enter submits and Shift+Enter newlines with IME composition respected, visible focus rings, skip link, `aria-live` job status, persisted light/dark, and a favicon cropped to the readable part of the mark | `web/src/keyboard.ts`, `web/index.html` |

### 3. Agentic capability and personalization — 50 points

| Criterion | What addresses it | Where |
|---|---|---|
| Understanding intent | A conversation-scoped technical profile — service, runtime, framework, deployment mode — extracted and carried as context across turns | `src/services/technical_profile.py` |
| Asking a follow-up when needed | Clarification is allowed only when the retrieved alternatives actually diverge on the missing detail; a clarification that would not change the answer is rejected and the model is made to answer | `src/services/agent.py` `_clarification_is_load_bearing` |
| Keeping context | Recent turns verbatim, older ones in a running incremental summary; each turn is summarized at most once | `src/services/summarization.py` |
| Personalized answers | The profile narrows retrieval filters, and a filter that matches nothing reports `NO_RESULTS_FOR_FILTER` rather than silently widening | `src/services/agent_tools.py` |
| Suggesting a next step | The FAQ gate names the next move explicitly; an abstention says what was searched and what was missing rather than stopping | `web/src/components/FaqGate.tsx` |
| Multi-step processes | An explicit bounded loop — tool calls and query rewrites capped in code, not asked for in the prompt — with every step observable | `src/services/agent.py` |
| Creative use of agentic capability | The same retrieval core is exposed three ways: web chat, an installable Skill for a coding agent, and an MCP server with strict tool schemas, so the answer a coding agent gets is the answer the site gives | `src/mcp/`, `.agents/skills/liara-docs-rescue/SKILL.md` |

Retrieved documentation is treated as untrusted data throughout. The system
prompt states the boundary, tool results are wrapped with an explicit
`untrusted_data_not_instructions` marker, and the conversation summary carries
the same marker — text recalled from a previous turn is data too.

### 4. Security, reliability, and monitoring — 50 points

| Criterion | What addresses it | Where |
|---|---|---|
| Rate limiting | Per-IP and per-session windows in Redis, returning the rate-limited code rather than a generic rejection | `src/services/rate_limit.py` |
| API keys and secrets | Keys live in Liara's secrets panel and a gitignored local `.env`; no credential reaches the frontend bundle; the admin console holds its password in memory only, never in browser storage | `src/core/config.py` `SECRET_FIELDS` |
| Error and failure handling | A closed taxonomy where every code carries its own Persian message, HTTP status, operator action, and retry classification | `src/core/errors.py`, `docs/deployment.md` §10 |
| Token and request control | A hard agent token budget, capped tool calls and rewrites, and a FAQ gate that calls no model until the user says the documentation did not help | `src/core/config.py` |
| Logging and monitoring | Structured JSON logs, Prometheus metrics, and a dashboard where every figure derives from a recorded event and an unmeasured metric reports its absence instead of rendering as zero | `src/services/dashboard.py`, `monitoring/` |
| Maintainable architecture | Jobs are persisted before they are enqueued and answered by a separate worker; SSE resumes from `Last-Event-ID`; a dead worker's lease expires and its job is reclaimed | `src/services/job_runner.py`, `src/services/jobs.py` |

*Planned:* secret redaction in log records (14.3), cross-process correlation ids
(14.5), Opik tracing spans (14.6), and per-request cost attribution (14.7).

### 5. Deployment on Liara — 40 points

| Criterion | What addresses it | Where |
|---|---|---|
| Running on Liara | API, worker, and a Portkey gateway container on Liara, with managed PostgreSQL + pgvector and Redis on a private network | `docs/deployment.md` §3–§4 |
| Deployment quality | Documented deploy order with the two failure modes that each cost a deploy, health endpoints separating liveness from readiness, and a rollback path | `docs/deployment.md` §9–§10 |
| Configuration | Every threshold, budget, model id, and timeout is an environment variable validated at startup; retrieval tuning is additionally admin-editable at runtime without a redeploy | `src/core/config.py`, `src/services/runtime_config.py` |
| Production readiness | Alembic for every schema change, immutable index versions with atomic activation and retained rollback targets, idempotency keys on submission | `alembic/`, `src/services/ingestion/` |

*Planned:* CI and gated deploy workflows with automatic rollback — tasks 17.1–17.5.

### 6. Cost optimization — 25 points

| Criterion | What addresses it | Where |
|---|---|---|
| Model and service choice | `gemini-3.7-flash` for chat and FAQ generation; embeddings at 1536 dimensions rather than the native 3072, which is both cheaper and the only size pgvector can HNSW-index | `docs/deployment.md` §2 |
| Token control | A hard agent token budget checked before and after every model call, with capped tool calls and rewrites | `src/services/agent.py` |
| Avoiding unnecessary requests | The FAQ path costs one embedding and no generation; the gate means a question the documentation already answers never reaches the model at all; history summarization keeps cost flat as a conversation grows instead of linear in its length | `src/services/faq.py`, `src/services/summarization.py` |
| Caching and reuse | Idempotency keys make a retried submission provably the same job; a reload rejoins the running job rather than starting a second one; a no-change reindex performs no embedding | `src/services/jobs.py` |
| Infrastructure cost | Sized and priced per service before provisioning, with the reasoning recorded | `docs/deployment.md` §4, §8 |
| Quality against cost | The two-stage design is the trade-off made explicit: cheap retrieval first, generation only when it is actually needed, and abstention rather than an expensive guess | — |

Token usage and cost per request are recorded as usage events and surfaced on
the dashboard, so the trade-off can be checked rather than asserted.
