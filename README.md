# Liara Documentation Rescue Assistant

**دستیار نجات مستندات لیارا** — a system for people who are stuck in Liara's
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

A stuck user writes their question in full — the error message, what they tried,
what they expected — and the system moves them through four stages:

1. **Related questions.** A semantic search over FAQ entries generated from the
   real documentation. Deliberately labelled *related questions*, not *answers*:
   they are matched by similarity, and calling them answers would promise more
   than the match justifies. No answer-generation model runs on this path, so it
   is fast and cheap.
2. **A judgement.** The user says whether that helped. "It did not" is recorded
   with the question and the pages implicated — that is the documentation-gap
   signal, stored rather than merely counted.
3. **Rescue tools.** Three ways out, described by the situation each suits
   rather than by what it is: a chat assistant, an installable Skill for a
   coding agent, and an MCP server. The original question travels into whichever
   one they pick; they never retype it.
4. **Grounded chat.** A bounded agent that answers from retrieved documentation
   only. Every technical claim carries a citation that deep-links to the section
   it came from. When the evidence is insufficient it abstains and says so
   rather than guessing.

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
| `RETRIEVAL_SIMILARITY_THRESHOLD` | `0.25` | Below this, results are suppressed and the gap is recorded. |
| `FAQ_SIMILARITY_THRESHOLD` | `0.4` | Admin-editable at runtime. |
| `FAQ_SHORT_QUERY_SIMILARITY_THRESHOLD` | `0.6` | Greetings and other tiny queries must clear a stronger relevance bar. |
| `FAQ_ITEMS_PER_DOCUMENT` | `15` | Upper bound for useful candidates; every accepted answer must be complete, precise, and sized to its evidence. |
| `FAQ_MAX_OUTPUT_TOKENS` | `12288` | Generation headroom, not a target length; answers must not be padded or fabricated. |
| `RETRIEVAL_DUPLICATE_THRESHOLD` | `0.9` | Near-identical passages consume one evidence slot. |
| `AGENT_TOKEN_BUDGET` | `32000` | Must hold one retrieval round (`RETRIEVAL_TOP_K` × `CHUNK_MAX_TOKENS` ≈ 9.6k) plus the answer. At the previous 8000, every well-retrieved question terminated as `AGENT_LIMIT_REACHED` before it could answer. |
| `AGENT_MAX_TOOL_CALLS` | `3` | Enforced in code, not requested in the prompt. |
| `MAX_CONVERSATION_TURNS` | `3` | The next draft starts a fresh rescue flow instead of growing unbounded context. |
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
  services/     ingestion, retrieval, faq, agent, jobs, job_runner
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
