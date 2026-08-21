# Deployment & Infrastructure Decisions

> Operational companion to `liara-docs-rescue-plan.md`.
> That document owns **product scope**. This one owns **infrastructure, configuration, and deploy sequence**.
> Where they disagree, this file wins on infrastructure and the plan wins on product.

**Status:** decisions locked, pre-implementation
**Timeline:** 2 days, one developer
**Target:** Liara

---

## 1. Locked decisions

| Area | Decision | Verified |
|---|---|---|
| Chat model | `gemini-3.7-flash` via AvalAI (added 2026-08-14) | ✅ $0.75 in / $3.75 out per 1M |
| FAQ generation model | `gemini-3.7-flash` — same model, separate env var so it can diverge | decided |
| Vision | Same model — native vision. **No separate vision model needed** | ✅ per model card |
| Agent tool calling | Native function calling + parallel calls + structured output | ✅ per model card |
| Embedding model | `text-embedding-3-large` via AvalAI | ✅ live call |
| Embedding dimensions | **1536** via `dimensions` request param | ✅ AvalAI honors it |
| Vector store | pgvector in PostgreSQL, `vector(1536)` + HNSW | ✅ extension available on Liara |
| Max input length | 8191 tokens/request — chunks target 500–800 | ✅ per AvalAI model card |
| Gateway | Portkey gateway **as a Liara service** (own container image), not Portkey's managed SaaS | decided |
| LLM observability | Opik **SaaS** (free tier) — the only external dependency, nothing to deploy | decided |
| Runtime telemetry | Prometheus metrics, Grafana dashboards/alerts, Loki logs, and Grafana Alloy collection; Opik remains the LLM/RAG trace backend | decided |
| Chat execution | Redis queue + Worker, SSE relay via Redis | decided |
| Web serving | React bundle served **from the API origin** (same-origin) | decided |
| Auth | Admin only — HTTP Basic from env. No end-user auth | decided |
| FAQ corpus | LLM-generated from docs, admin-curated, admin `sync` button | decided |
| Ingest scope | Config-driven section allowlist | decided |
| MCP | Kept, last-phase priority | decided |
| Persian normalization | Custom normalizer (ی/ي, ک/ك, ZWNJ, digits, spacing) | decided |
| FAQ threshold | **Cosine similarity**, admin-editable, default 0.34 | decided |

### Still open

- Persian answer quality for `gemini-3.7-flash`. Spot-check ~10 questions before locking it for live chat; if it disappoints, only `LLM_MODEL` changes — `FAQ_LLM_MODEL` can stay.
- `pg_trgm` availability on Liara. Not in the extension toggle; `tsvector` alone is an acceptable fallback.

---

## 1b. Model capabilities and what they unlock

`gemini-3.7-flash` (released 2026-08-13) is more capable than the plan assumed. Several open questions collapse as a result.

| Capability | Consequence for this build |
|---|---|
| **Function calling** + parallel calls | The bounded agent's allowlisted tools run natively. No prompt-based tool emulation, no parsing fragile text output. |
| **Structured output** | FAQ generation emits schema-validated JSON. Removes an entire class of parse-failure retries from the bulk job. |
| **Vision** (image, video, PDF input) | The §12.2 vision fallback needs **no separate model or env var**. It becomes a prompt variant on the same client — cheap enough to reconsider its P1 status. |
| **Prompt caching** ($0.075/1M, 10× cheaper) | The FAQ system prompt repeats across ~1,142 calls. Cache it. |
| **Streaming** | SSE path confirmed. |
| **`reasoning_effort`: low / medium / high** | Use `low` for bulk FAQ extraction, `medium` for live chat. Reasoning tokens bill as output — this is a direct cost lever. |
| **1,048,576-token context** | Context window is a non-constraint. Retrieval quality still matters — never dump whole docs in; irrelevant context degrades answers regardless of fit. |
| **`/v1/batch` endpoint** | Available for the FAQ job. Skipped for v1 — async batch adds orchestration for a job that already finishes in minutes. |

**Rate limits at your Tier 4:** 3,500 RPM / 5,000,000 TPM. The FAQ job is nowhere near either ceiling.

> One caution on the benchmarks in the AvalAI announcement: they measure coding and agentic tasks in English. Nothing there predicts Persian answer quality on Liara's docs — which is your 80-point criterion. That is exactly what your own eval set is for.

---

## 2. Why 1536 dimensions

Not an arbitrary choice — pgvector's index limits force it:

```
vector   → stores up to 16,000 dims, but HNSW/IVFFlat index caps at 2,000
halfvec  → index up to 4,000 dims, requires pgvector >= 0.7.0

text-embedding-3-large default = 3072  ✗ unindexable as `vector`
                    dimensions = 1536  ✓ indexable, half the storage
```

At 3072 with plain `vector`, every query degrades to a sequential scan. 1536 keeps HNSW available with no pgvector version dependency. Recall loss is negligible — the model is Matryoshka-trained, so leading dimensions carry the most signal.

**Record the actual dimension in index metadata.** If it ever changes, every stored vector is invalidated and a full reindex is mandatory.

---

## 3. Service topology

```
                    ┌──────────────────────────────┐
   browser ────────▶│  API (FastAPI)  +  Web bundle │  same origin
                    │  1 GB                         │  → no CORS, cookies just work
                    └───┬────────┬─────────┬────────┘
                        │        │         │
              ┌─────────┘        │         └──────────┐
              ▼                  ▼                    ▼
      ┌───────────────┐  ┌──────────────┐   ┌──────────────────┐
      │ PostgreSQL    │  │ Redis        │   │ Portkey Gateway  │
      │ + pgvector    │  │ 0.5 GB       │   │ 0.5 GB           │
      │ 2 GB          │  │              │   └────────┬─────────┘
      └───────▲───────┘  └──────▲───────┘            │
              │                 │              ┌─────┴──────┐
              │                 │              ▼            ▼
              │          ┌──────┴───────┐   AvalAI      fallback
              └──────────│ Worker 1 GB  │   (primary)   provider
                         └──────────────┘
```

**Nine deployed services plus Opik SaaS.** The monitoring services are isolated
from the user request path: telemetry delivery failure must never fail a rescue
request.

| Service | Plan | Rationale |
|---|---|---|
| PostgreSQL | **2 GB** | 12k chunks × 1536 dims ≈ 74 MB of vectors + ~150 MB HNSW index. 1 GB works until the index build; 2 GB gives `maintenance_work_mem` headroom. The only service worth paying up for. |
| Redis | 0.5 GB | Queue, cache, rate limits, SSE relay. Data footprint is trivial. |
| API + Web | 1 GB | uvicorn plus concurrently-held SSE connections. |
| Worker | 1 GB | Ingestion peak. Stream files — never load all 1,142 at once. |
| Portkey | 0.5 GB | Single Node container. |
| Prometheus | 4 GB | Metrics retention and load-test analysis; persistent disk required. |
| Grafana | 2 GB | Dashboards and alerts; persistent disk and admin secret required. |
| Loki | 4 GB | Single-binary structured-log retention for this deployment; persistent disk required. |
| Grafana Alloy | 1 GB | Receives application telemetry and forwards logs without requiring host-level Docker access. |

### Environments: local development vs Liara

Nothing is "self-hosted" in the sense of a machine you administer. There are exactly two environments, and every service exists in both:

| | Local development | Production |
|---|---|---|
| Orchestration | Docker Desktop + `docker compose` | Liara services |
| Postgres + pgvector | container from compose | Liara managed Postgres, Pgvector extension enabled |
| Redis | container from compose | Liara managed Redis |
| API + Web | container, hot reload | Liara app service |
| Worker | container | Liara app service |
| Portkey gateway | container from compose | Liara app service from the same image |
| Prometheus | container with a named volume | Liara app service with a persistent disk |
| Grafana | container with a named volume | Liara app service with a persistent disk |
| Loki | single-binary container with a named volume | Liara app service with a persistent disk |
| Grafana Alloy | container | Liara app service |
| Opik | SaaS — same endpoint from both | SaaS |
| Config | `.env` file, gitignored | Liara secrets panel |

**The Portkey gateway is our own container image in both environments** — we run the open-source gateway rather than calling Portkey's managed SaaS. In development it comes up with `docker compose up`; in production Liara runs the same image as an app service.

**Opik remains the single external SaaS dependency.** Nothing about it is
deployed; both environments call the same hosted endpoint. Prometheus,
Grafana, Loki, and Alloy are project-owned containers. Running Opik ourselves
is out of scope — its stack needs ClickHouse, MySQL, MinIO, and more.

`docker-compose.yml` must bring the whole stack up locally with one command, so the dev/prod gap stays small and the same images ship to Liara.

### Why Web is merged into the API

Two problems solved by one decision:

1. **Cookies.** Separate subdomains would force `SameSite=None; Secure` plus credentialed CORS, fighting the "CORS محدود" requirement. Same-origin means `SameSite=Lax` and zero config.
2. **Cost + one less deploy target.**

FastAPI mounts the Vite build output as static files with an SPA catch-all. API routes live under `/api/v1` and never collide.

---

## 4. Liara provisioning

Run this at the **start of implementation**, not before — Liara bills hourly and idle services burn credit. Verified against CLI `@liara/cli/9.5.1`.

> ⚠️ **The CLI cannot enable database extensions.** `liara db` offers only `create`, `list`, `remove`, `resize`, `start`, `stop`, and `backup`. Enabling Pgvector is a **manual panel step** and there is no automated substitute. Because enabling it restarts the database, do it immediately after creation while the database is still empty.

### Sizing and cost

Plans and prices below are from `liara plan:list` on this account. The current
deployment is intentionally sized for a validation target of **300 concurrent
users**. This is a capacity assumption, not a performance claim: the deployed
chat path must still pass a representative load test, and upstream model
concurrency/rate limits remain a separate bottleneck that larger Liara machines
cannot remove.

| Service | Plan | RAM | تومان/ماه |
|---|---|---:|---:|
| PostgreSQL | existing `standard-pro-g2` | existing | existing |
| Redis | `standard-base-g2` + Pro bundle | 2 GB | 1,050,000 |
| API + Web | `pro-g2` + Gold bundle | 8 GB | 3,300,000 |
| Worker | `standard-base-g2` + Gold bundle | 2 GB | 1,050,000 |
| Portkey gateway | `pro-g2` + Gold bundle | 8 GB | 3,300,000 |
| Prometheus | `standard-plus-g2` + Gold bundle | 4 GB | 1,900,000 |
| Grafana | `standard-base-g2` + Gold bundle | 2 GB | 1,050,000 |
| Loki | `standard-plus-g2` + Gold bundle | 4 GB | 1,900,000 |
| Grafana Alloy | `medium-g2` + Gold bundle | 1 GB | 600,000 |
| **New capacity subtotal** | | **31 GB** | **≈ 14,150,000** |

The subtotal excludes the already-provisioned PostgreSQL service. Right-size
only after observing CPU, memory, database pool pressure, queue depth, gateway
latency, and provider throttling during the 300-user test.

### Steps

1. **Create PostgreSQL, or reuse the project database already provisioned for
   this deployment.** The current deployment uses `liaradb` on
   `standard-pro-g2`.

   ```bash
   liara db:create --name liara-rescue-db --type postgres --plan standard-base-g2
   ```

2. **Enable Pgvector — manual, in the panel.** Open the database → تنظیمات افزونه → toggle **Pgvector** → ثبت تغییرات. Accept the restart. Do this before any data exists.

3. **Verify the extension and its version.** `halfvec` needs ≥ 0.7.0; the 1536-dim path does not depend on it, so this is informational.

   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   SELECT extversion FROM pg_extension WHERE extname = 'vector';
   ```

4. **Check the lexical fallback** (open question in design.md):

   ```sql
   SELECT * FROM pg_available_extensions WHERE name = 'pg_trgm';
   ```

5. **Create Redis.**

   ```bash
   liara db:create --name liara-rescue-redis --type redis --version 7.2.3 \
     --plan standard-base-g2 --feature-plan pro --network liara-challenge
   ```

6. **Create the three app services.**

   ```bash
   liara app:create --app liara-rescue-api --platform docker \
     --plan pro-g2 --feature-plan pro --network liara-challenge
   liara app:create --app liara-rescue-worker --platform docker \
     --plan standard-base-g2 --feature-plan pro --network liara-challenge
   liara app:create --app liara-rescue-gateway --platform docker \
     --plan pro-g2 --feature-plan pro --network liara-challenge
   ```

7. **Put database and Redis on the same private network as the apps** so connection URIs use the private network rather than the public internet. `db:create` and `app:create` both accept `--network`.

8. **Create the monitoring services on the same private network.** Grafana may
   expose HTTPS and requires a rotated admin secret. Prometheus, Loki, and
   Alloy remain private. Attach the provisioned disks `prometheus-data`
   (**40 GB**) at `/prometheus`, `grafana-data` (**10 GB**) at
   `/var/lib/grafana`, and `loki-data` (**40 GB**) at `/loki` before the first
   production deployment.

   ```bash
   liara app:create --app liara-rescue-prometheus --platform docker \
     --plan standard-plus-g2 --feature-plan pro --network liara-challenge
   liara app:create --app liara-rescue-grafana --platform docker \
     --plan standard-base-g2 --feature-plan pro --network liara-challenge
   liara app:create --app liara-rescue-loki --platform docker \
     --plan standard-plus-g2 --feature-plan pro --network liara-challenge
   liara app:create --app liara-rescue-alloy --platform docker \
     --plan medium-g2 --feature-plan pro --network liara-challenge
   ```

   Production images are pinned in `monitoring/*/Dockerfile`: Prometheus
   `v3.13.2`, Grafana `13.1.0`, Loki `3.7.4`, and Alloy `v1.17.1`. Prometheus
   retains 15 days of metrics. Loki automatic deletion is disabled because its
   filesystem delete store times out on a Liara persistent disk; the 40 GB disk
   is the current log-capacity limit. Add a compatible object-store/delete
   backend before enabling time-based Loki retention, and measure disk growth
   during the 300-user test. Liara mounts this persistent disk root-owned, so
   the Loki container currently runs as root; keep the service private and
   replace this exception if Liara adds configurable disk ownership.

   The project intentionally does not deploy the Kubernetes-oriented
   `daviaraujocc/lgtm-stack`: it adds Helm, Mimir, Tempo, MinIO, and scalable
   multi-process Loki assumptions that do not match this Liara PaaS topology.
   Liara's one-click Grafana template is also insufficient by itself because
   it provisions only Grafana and a disk, not Prometheus, Loki, or the OTLP
   collector.

9. **Set env vars through the Liara panel's secrets UI.** Never deploy a `.env` file.

### Provisioning status (verified 2026-08-21)

The Liara team selected by the local, gitignored `LIARA_TEAM_ID` currently has the existing
`liaradb` PostgreSQL service plus `liara-rescue-redis`, `liara-rescue-api`,
`liara-rescue-worker`, `liara-rescue-gateway`, `liara-rescue-prometheus`,
`liara-rescue-grafana`, `liara-rescue-loki`, and `liara-rescue-alloy`. All were
created on private network `liara-challenge`; the three monitoring disks above
were also created. A read-only production SQL check on 2026-08-21 confirmed
`vector` 0.8.1 and `pg_trgm` 1.6 are installed. The pinned gateway, Prometheus, Grafana,
Loki, and Alloy releases have each passed their public HTTPS health endpoint.
**Released 2026-08-21.** The gateway, API, and worker now each have a healthy
release. `alembic -x target=liara upgrade head` brought the managed database to
`dbd77a4b7a1e` with all eleven tables, `vector` 0.8.1, `pg_trgm` 1.6, and the
HNSW index present. On `https://liara-rescue-api.liara.run`, `/health/live`
returns 200 and `/health/ready` reports Postgres, Redis, and the gateway
healthy. The 300-user load test remains a deployment gate.

Ingestion then ran against the managed database through the deployed gateway,
producing **3,776 chunks across 1,142 documents** at upstream commit `dbb7430`,
index version `a60589fd`, all validation checks passing. `/health/ready` now
returns **200** with Postgres, Redis, the active index, and the gateway all
healthy — task 2.6 closed.

The MCP server is live at `https://liara-rescue-api.liara.run/mcp`, verified from
Claude Code and Codex. See [`mcp.md`](mcp.md).

> **Liara's edge strips the readiness body when the check fails.** While
> `/health/ready` was 503 it returned a **zero-length body** at the public URL,
> even though the application emitted the full per-dependency JSON — the logs
> show the response it produced. Diagnose a failing readiness check from
> `liara logs`, never from the public response body, which in that state carries
> the status code and nothing else.

> **Forced FAQ regeneration is explicit.** The normal command skips unchanged
> source hashes. To rebuild the expanded corpus, run
> `uv run python -m scripts.generate_faq --force`. Each document is replaced in
> its own transaction: its old active entries remain available if generation or
> validation fails, and are deactivated only when a valid replacement set commits.

> **Account hygiene.** This account already hosts `royara-api`, `royara-db`, and `makeupapp`, which are unrelated to this project. Every name above is prefixed `liara-rescue-` so nothing collides, and no existing resource is touched.

---

## 5. Configuration

`.env` is for local development only and must be listed in `.gitignore`. Production values live in Liara secrets.

```env
# --- Runtime ---
APP_ENV=local
LOG_LEVEL=INFO
WEB_DIST_DIR=web/dist
SKILL_FILE_PATH=.agents/skills/liara-docs-rescue/SKILL.md

# --- Chat LLM ---
LLM_BASE_URL=https://api.avalai.ir/v1
LLM_API_KEY=<from-liara-secrets>
LLM_MODEL=gemini-3.7-flash

# --- Bulk FAQ generation: separate var so it can diverge from chat ---
# Item/token values are ceilings. The prompt requires complete, precise,
# evidence-sized answers and forbids padding or fabrication to fill either one.
FAQ_LLM_MODEL=gemini-3.7-flash
FAQ_REASONING_EFFORT=low       # reasoning bills as output; keep bulk extraction cheap
FAQ_ITEMS_PER_DOCUMENT=15
FAQ_MAX_OUTPUT_TOKENS=12288   # output room, not a required answer length
FAQ_GENERATION_TIMEOUT_SECONDS=120
FAQ_GENERATION_CONCURRENCY=20

# --- Embeddings (verified working) ---
EMBEDDING_BASE_URL=https://api.avalai.ir/v1
EMBEDDING_API_KEY=<from-liara-secrets>
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=1536

# --- Gateway ---
PORTKEY_BASE_URL=http://portkey:8787

# Secondary provider. Candidates, both OpenAI-compatible:
#   Vercel AI Gateway  — https://ai-gateway.vercel.sh/v1
#   GapGPT             — OpenAI-compatible, Iran-reachable
PORTKEY_FALLBACK_BASE_URL=
PORTKEY_FALLBACK_API_KEY=
PORTKEY_FALLBACK_MODEL=

# --- Evaluation ---
EVAL_JUDGE_MODEL=          # MUST differ from LLM_MODEL — see §13

# --- Infrastructure ---
DATABASE_URL=
REDIS_URL=

# --- Ingestion scope: full corpus. Narrow via this list if day 1 runs long ---
DOCS_REPO_URL=https://github.com/liara-cloud/docs
DOCS_REPO_BRANCH=master
INGEST_SECTIONS=*
INGEST_EXCLUDE_GLOBS=
CHUNK_TARGET_TOKENS=700
CHUNK_OVERLAP_TOKENS=80
CHUNK_MIN_TOKENS=120           # below this, a chunk is merged with its neighbour
CHUNK_MAX_TOKENS=1200          # above this, a chunk is split
INGEST_DISCARD_RATIO_THRESHOLD=0.35   # §7 guardrail: flag a file for review above this
DOCS_CACHE_DIR=.cache/docs     # checkout kept between runs; unchanged upstream costs a fetch
DOCS_BASE_URL=https://docs.liara.ir   # public site citations point at, not the repo
EMBEDDING_BATCH_SIZE=16        # work a single retry repeats, not a context limit
EMBEDDING_TIMEOUT_SECONDS=120  # a merely-slow request must not be retried as a failure
INDEX_RETENTION_COUNT=2        # superseded versions kept; at least 1 or rollback has no target

# --- Retrieval ---
# Relaxed 15% from 0.4/0.6/0.25 after live use: questions phrased in a user's
# own words were landing just under the old bars and returning nothing.
FAQ_SIMILARITY_THRESHOLD=0.34   # cosine SIMILARITY, not pgvector distance
FAQ_SHORT_QUERY_MAX_CHARS=8
FAQ_SHORT_QUERY_SIMILARITY_THRESHOLD=0.51   # suppress greetings matching unrelated FAQs
FAQ_TOP_K=5
FAQ_CANDIDATE_MULTIPLIER=4    # over-fetch so dedupe can still fill the requested slots
FAQ_PRIORITY_WEIGHT=0.01       # ordering only: similarity + priority * weight; never changes exposed similarity
RETRIEVAL_TOP_K=8
RETRIEVAL_CANDIDATE_MULTIPLIER=3
RETRIEVAL_DUPLICATE_THRESHOLD=0.9
RETRIEVAL_SIMILARITY_THRESHOLD=0.2125   # below this is NO_RESULTS_ABOVE_THRESHOLD
RRF_K=60
RRF_DENSE_WEIGHT=1.0
RRF_LEXICAL_WEIGHT=1.0
RETRIEVAL_METADATA_BOOST_WEIGHT=0.15   # soft multiplier per matching profile field
INDEX_STALE_AFTER_DAYS=14      # past this, answers carry INDEX_STALE

# --- Agent bounds: enforced in the loop, never merely requested in the prompt ---
AGENT_MAX_TOOL_CALLS=3
AGENT_MAX_REWRITES=2
AGENT_TOKEN_BUDGET=32000
AGENT_TIMEOUT_SECONDS=60
MAX_QUESTION_CHARS=2000
MAX_HISTORY_TURNS=3            # turns replayed verbatim; older ones are summarized
MAX_CONVERSATION_TURNS=40      # abuse ceiling only — no longer the product's turn limit

# --- Conversation summarization ---
# Past the trigger, turns outside MAX_HISTORY_TURNS are folded into a running
# summary. Each turn is summarized once, so cost stays flat as a thread grows.
CONVERSATION_SUMMARY_TRIGGER_TURNS=3
CONVERSATION_SUMMARY_MODEL=            # blank falls back to LLM_MODEL
CONVERSATION_SUMMARY_MAX_TOKENS=800
CONVERSATION_SUMMARY_TIMEOUT_SECONDS=30

# --- Rate limiting ---
RATE_LIMIT_PER_IP_PER_MINUTE=30
RATE_LIMIT_PER_SESSION_PER_MINUTE=15

# --- Admin ---
ADMIN_USERNAME=
ADMIN_PASSWORD=

# --- Observability ---
OPIK_API_KEY=
OPIK_WORKSPACE=
```

> **Threshold units.** pgvector's `<=>` returns cosine *distance* (`1 - similarity`). Store and expose **similarity** everywhere — in the admin field, the API, and the logs — so `0.4` never means two different things in two places.

---

## 6. Ingestion scope

**v1 ingests the full corpus** — all 12 top-level sections of `src/pages`:

```text
ai   dbaas   dns-management-system   email-server   iaas   mirrors
object-storage   one-click-apps   overview   paas   references   tv
```

Full coverage means no user question falls outside the index, which directly serves the answer-quality criterion. Cost is not a factor (§8) and embedding wall-clock is 1–2 minutes.

**`INGEST_SECTIONS` is the pressure valve, not the plan.** The real cost of breadth is pre-pass debugging — each section can introduce JSX component patterns the transform table doesn't cover yet. If day 1 runs long, narrow to `paas,dbaas,iaas,overview` (which covers the demo scenario), ship, then widen with a config edit and a re-run. Never a refactor.

Two sub-trees to watch when reviewing pre-pass output quality:

| Path | Why it's different |
|---|---|
| `ai/ai-sdk-core`, `ai/ai-sdk-errors`, `ai/ai-sdk-ui`, `ai/cookbook` | Vercel AI SDK reference — large, largely English, likely the biggest token block in the repo. Fine to index; just don't let its volume skew retrieval toward it on Persian questions. Check its share of top-k results during eval. |
| `references` | Reference tables rather than prose — verify chunking doesn't split tables from their headers. |

---

## 6b. Backend project layout

Adapted from the FastAPI Starter Kit reference (`github.com/esmaeil-taheri/FastAPI-Starter-Kit`), taking the parts that pay for themselves in two days and leaving the parts that don't.

```text
src/
  core/            config (pydantic-settings), structured logging, error codes
  api/v1/          routers registered centrally in routes.py
  db/
    models/        SQLAlchemy 2.x async models
    session.py
  services/        ingestion, retrieval, faq, agent, eval
  mcp/             MCP tool definitions over the shared retrieval core
  main.py          ASGI entry point, mounts the built web bundle
alembic/           env.py + versions/    ← migrations, mandatory
scripts/           ingest, generate-faq, run-eval, reindex
tests/             unit/ and integration/
docker/            Dockerfile.dev, Dockerfile.prod
web/               React/Vite source; build output served by the API
```

**Adopted from the reference:**

- **Alembic for every schema change.** No hand-written DDL, no `create_all` in application code. `alembic/env.py` reads the database URL from settings so dev and production share one migration path. In production, the API entrypoint applies migrations before Uvicorn starts; a migration failure exits the new container before it can receive traffic. The Worker does not migrate.

  Which database a run targets is selected explicitly, never implicitly:

  | Command | Targets | Used by |
  |---|---|---|
  | `alembic upgrade head` | `DATABASE_URL` | Local compose (run inside the container, where `postgres` resolves) and the production API entrypoint, where it is the private-network address |
  | `alembic -x target=liara upgrade head` | `LIARA_DATABASE_URL` | An operator machine migrating the managed database over its external connection URL |

  There is no implicit fallback from one to the other. A migration that silently
  reached production because a variable was unset is the accident this prevents.
- **Async SQLAlchemy 2.x with asyncpg** — matches FastAPI's concurrency model and matters here because retrieval and provider calls both block on I/O.
- **`pydantic-settings` for typed configuration** loaded from environment, with `.env` used only locally.
- **Central route registration** in one `routes.py` rather than scattered decorators.
- **`scripts/`** for operational entry points — ingestion, FAQ generation, and evaluation are all long-running jobs that must be runnable outside a request.
- **Split dev/prod Dockerfiles** and structured logging in `core/`.

**Deliberately not adopted:** the full Clean Architecture split (`domain` / `application` / `infrastructure` / `presentation`) and a dependency-injection container. Both are sound for a long-lived multi-developer codebase; across two days and one developer they add indirection without buying testability we'd otherwise lack. RBAC and user management from the reference are irrelevant — there is no end-user auth here.

---

## 7. MDX pre-pass

Content is Next.js Pages Router + `@next/mdx` v3. Every file wraps content in `<Layout>` and imports custom components.

> **Critical:** section headings are **not** Markdown. They are `<Section id="…" title="…" />` JSX components. A Markdown-only parser sees one undifferentiated blob per file and chunking silently collapses.
>
> The upside: `id` and `title` are explicit, so `heading_anchor` and `section` metadata come free and citations deep-link as `{source_url}#{id}`.

> **Equally critical, and the correction that cost the most:** the corpus contains **zero Markdown code fences**. All 3,731 code blocks are ``<Highlight className="lang">{`…`}</Highlight>`` — the code lives *inside* a JSX expression container. A rule that drops `{ … }` blocks wholesale discards every command, every `liara.json`, and every configuration snippet in the documentation, and does so without erroring. Expression blocks are dropped only when they are computed; a bare string or template literal is content and is kept.

Two stages: a JSX pre-pass producing clean Markdown, then `mistune` in AST mode (`create_markdown(renderer=None)`) for section-aware chunking.

Rules are keyed on the tag name, dispatched by JSX's own convention — **capitalized is a component, lowercase is HTML** — so `<Section>` (a heading) and `<section>` (a wrapper), or `<Link>` (next/link) and `<link>` (a void metadata element), can never be conflated.

| Source construct | Uses | Transform |
|---|---:|---|
| `import …` / `export …` | 1,143 files | drop (multi-line brace forms included) |
| `<Layout>` wrapper | 1,143 | unwrap |
| `<Head>…</Head>`, `<meta>`, `<title>` | 1,144 | drop; keep `<title>` as the document title. Excluded from the discard ratio — it is metadata, not content |
| `<Section id="X" title="Y" />` | 1,301 | `## Y` + record anchor `X`; `headingTag="h3"` → `### Y` |
| `` <Highlight className="L">{`…`}</Highlight> `` | 3,731 | fenced code block in language `L` — **not** a blockquote |
| `<Important>…</Important>` | 8,666 | inline code span — it is an inline badge, **not** a callout |
| `<Alert variant="…">…</Alert>` | 1,595 | blockquote — the only true callout of the three |
| `<Link href="X">Y</Link>` | 808 | `[Y](X)` |
| `<a href="X" className="…">Y</a>` | — | `[Y](X)` — **keep the link**, drop the styling |
| `<Tabs tabs={[{label}]} content={[…]} />` | 397 | flatten: `**label**` then the rendered tab body. Nests inside itself |
| `<Step steps={[{step, content}]} />` | 254 | `**n**` + rendered content; the whole block is recorded as one atomic region so it stays in one chunk with its images and code |
| `<HighlightTabs tabs={[{label, language, code}]} />` | 20 | `**label**` + a fence per tab |
| `<Table headers={[…]} data={[[…]]} />` | 78 | Markdown table |
| `<QuestionBox id question answer={…} />` | 5 | `### question` + rendered answer; `id` is the anchor |
| `<TickIcon>` `<TickBadge>` | 344 | `✔` — in a `<Table>` support matrix these *are* the cell value |
| `<Card>` `<Button>` `<PlatformIcon>` `<Asciinema>` `<Go*>` icons | ~1,100 | drop — navigation and decoration only |
| `<video>` `<iframe>` `<audio>` | 415 | drop — no text and no alt attribute |
| `{ /* … */ }` JSX comments | — | drop, and **exclude from the discard ratio** — content upstream deliberately disabled is not content lost |
| `{ … }` computed expressions (`.map()` card grids, icon props) | — | drop, and count against the discard ratio |
| `{ "…" }` / ``{ `…` }`` literals | — | **keep** — this is where all code and much prose lives |
| `<div>` `<p>` `<b>` `<hr className=…>` `<ul>` `<img>` | — | strip tag, keep text; `<img>` → `![alt](src)` and record the image |

> **Match on the JSX tag name, never the import path.** Verified across three files: `paas/about.mdx` imports `Tabs` from `@/components/Common/tabs` while `paas/django/getting-started.mdx` imports it from `@/components/Common/tab` (singular). The repo is internally inconsistent. Tag names are stable; import paths are not.

**Guardrail metric.** Record the proportion of *content* characters discarded per file — content meaning text and expression bodies, not tag markup, imports, or `<Head>`. Liara owns this repo and can add components at any time; without this metric a new component degrades retrieval silently. Files above `INGEST_DISCARD_RATIO_THRESHOLD` are flagged for review, and every unrecognized tag name is returned with its frequency alongside the ratio.

Measured over all 1,143 documents at commit `dbb7430`: 76% of files discard nothing, median 0.000, p90 0.428, mean 0.090; 123 files (10.8%) exceed the configured 0.35. The flagged population is dominated by section index pages (`*/about.mdx`) that are almost entirely `.map()`-generated navigation cards with little prose — a true reading, not a defect. The one genuine content loss found is `ai/hugging-face.mdx`, whose list of supported models is `.map()`ed over an `export const` the pre-pass strips.

**Test assertion.** No `<` or `{` may survive into the text destined for embedding, measured on prose — fenced and inline code are exempt, because `<LIARA_API_KEY>`, `${VAR}`, and JSON braces are content that must reach the embedding intact. Corpus-wide, four documents still contain a bare `<` in prose: three are version comparisons inside tab labels (`redis < 7`, `Laravel < 11`, `NextJS < 12.2`) and one is malformed upstream markup (`< div className="h-2" />` in `ai/foundations/tools.mdx`). None is unstripped JSX; the invariant that must hold everywhere is that no `<` is ever glued to an identifier or a slash.

---

## 8. Cost model

Verified: `estimated_cost.unit = 0.00000013` → **$0.13 / 1M tokens**, USD-denominated.

Confirmed rates, USD per 1M tokens:

| | Input | Cached input | Output |
|---|---:|---:|---:|
| `text-embedding-3-large` | $0.13 | — | — |
| `gemini-3.7-flash` | $0.75 | $0.075 | $3.75 |

> Gemini promotional pricing runs to **2026-12-31**, after which rates double ($1.50 / $0.15 / $7.50). Irrelevant for the competition; relevant if this becomes a real service.

**One-time indexing, full corpus (~1,142 docs, ~1.8M cleaned tokens):**

| Item | Tokens | Cost |
|---|---:|---:|
| Doc chunk embeddings | ~1.8M | $0.23 |
| FAQ question embeddings (~5.7k questions) | ~114k | $0.02 |
| FAQ generation — doc content in | ~1.8M | $1.35 |
| FAQ generation — system prompt in (cached) | ~914k | $0.07 |
| FAQ generation — out (5 Q&A × 1,142) | ~685k | $2.57 |
| **Total** | | **≈ $4.25** |

**Runtime:** ~4k context in + ~600 out ≈ **$0.005/query**. A thousand demo queries ≈ $5. A 20-question eval suite run three times ≈ $0.32.

**Total project spend is under $20.** Stop optimizing cost — the §20.2 measures (FAQ fast path, Skill/MCP routing, caching, token budgets) stay in scope because they are the *product story* for the 25-point criterion and because they cut latency, not because the money matters.

**Wall-clock is the only real constraint.** At Tier 4 (3,500 RPM / 5M TPM), the FAQ job is bound by generation latency, not limits: ~1,142 calls at ~20-way concurrency ≈ **8–15 minutes**, unattended. Embeddings finish in 1–2 minutes.

**Cost levers, in order of effect:** `reasoning_effort=low` on bulk FAQ generation (reasoning bills as output, the most expensive line above) → prompt caching on the FAQ system prompt → chunk-count discipline.

---

## 9. Deploy sequence

**Deploy on hour 1, not day 2.** The Skill depends on MCP, which depends on a reachable API, which depends on a live index. Nothing in that chain is verifiable until deployment works — so prove the pipeline while it's still trivial.

```
hour 1   walking skeleton: API hello + Web hello + PG + Redis, /health/ready green
  ↓
day 1    ingestion → embeddings → retrieval → chat → queue/worker → FAQ generation
  ↓
day 2    UI → Skill → admin → dashboard → Portkey/Opik → guardrails → MCP → demo
```

Each deploy: build immutable versioned image → deploy API (entrypoint runs migrations before Uvicorn) → poll `/health/ready` → deploy Worker → verify its health check → roll back the application image on failure. Database revisions remain backward-compatible with the previous image because an image rollback does not automatically downgrade the schema.

### Deploying the three application services

Each service names its own Liara config, so a deploy is one command with no
flags to remember and nothing to get wrong at 3am:

```bash
liara deploy --team-id "$LIARA_TEAM_ID" --liara-json liara.api.json   --dockerfile docker/Dockerfile.prod
liara deploy --team-id "$LIARA_TEAM_ID" --liara-json liara.worker.json   --dockerfile docker/Dockerfile.prod
liara deploy --team-id "$LIARA_TEAM_ID" --path docker/gateway
```

**One image, two roles.** The API and the Worker deploy the *same* image from
`docker/Dockerfile.prod` and differ only in `APP_ROLE` (`api` | `worker`), which
`docker/entrypoint.sh` dispatches on. Two images would be two things to keep in
step, and the first time they drifted the symptom would be a worker running
older retrieval code against a newer index — invisible except as worse answers.

**API owns migrations.** Its entrypoint runs `alembic upgrade head` before
Uvicorn and exits immediately if Alembic fails, so the incompatible release
never accepts traffic. Deploy API before Worker. The Worker deliberately skips
migrations, preventing concurrent containers from racing the same revision.

`entrypoint.sh --check` is the container health probe and is role-aware: HTTP
`/health/live` for the API, and PID-1 identity for the Worker, which listens on
no port. Liara still requires a `port` for a worker app; nothing serves it.

**Liara health-check bounds.** `healthCheck.startPeriod` must be **≤ 3000 ms**.
A larger value is rejected at upload with `CODE 400` before anything builds.

### Two failure modes that cost a deploy each

Both were configuration, and both crashed the container at import time with a
message that named the real cause — which is the only reason they took minutes
rather than hours. Neither is a code defect; both are worth knowing.

| Symptom | Cause |
|---|---|
| `METRICS_PATH must be an absolute non-root path`, value `C:/Program Files/Git/metrics` | `liara env:set` run from **Git Bash**. MSYS path conversion rewrites any argument that looks like a Unix absolute path into a Windows one *before* the CLI sees it. `DOCS_CACHE_DIR=/app/.cache/docs` was mangled the same way. |
| Deploy reports the container unhealthy, logs show the previous release's traceback | Liara serves the last release's logs while no healthy release exists. Fix the cause and redeploy; do not read the stale trace as the new failure. |

**Set any variable whose value begins with `/` from PowerShell, or prefix the
command with `MSYS_NO_PATHCONV=1`.** Verify afterwards with `liara env:list` —
the mangling is silent, and the first sign of it is a container that will not
boot.

**Index safety.** Never mutate the active index in place. Write a new `index_version`, validate it with smoke queries, then flip activation atomically. Retain the previous healthy version. A failed reindex must leave the running index untouched.

---

## 10. Health, diagnostics & rollback

**Governing rule: every error must name its own cause.** "چیزی پیدا نکردم" is forbidden as a catch-all — an empty result and an empty index are different failures with different fixes, and collapsing them hides outages behind what looks like a normal answer.

### Health endpoints

`GET /health/live` — the process is up. Nothing else.

`GET /health/ready` — returns per-dependency status, never a bare boolean:

```json
{
  "ready": false,
  "checks": {
    "postgres":     { "ok": true,  "latency_ms": 3 },
    "redis":        { "ok": true,  "latency_ms": 1 },
    "active_index": { "ok": false, "reason": "no_active_index_version" },
    "gateway":      { "ok": true,  "provider": "avalai" }
  }
}
```

`ready` is false if **any** check fails, so Liara withholds traffic and the previous healthy release stays live. `active_index` is the one people forget: without it a fresh deploy passes health checks and serves confident empty answers.

### Error taxonomy

Every failure carries a stable machine code, a Persian user-facing message that states the actual cause, and an operator action. The distinction that matters most is the first two rows — they look identical to a user but have nothing in common.

| Code | Cause | Persian message | Operator action |
|---|---|---|---|
| `NO_ACTIVE_INDEX` | Ingestion never ran, or activation failed | «هنوز هیچ مستندی ایندکس نشده است. این یک خطای سیستمی است، نه نبود پاسخ.» | Run ingestion; check the last `index_versions` row |
| `NO_RESULTS_ABOVE_THRESHOLD` | Index healthy, nothing scored above threshold | «مستندات ایندکس شده‌اند، اما پاسخی مرتبط با این سؤال پیدا نشد.» | Genuine gap — log to unresolved analytics |
| `NO_RESULTS_FOR_FILTER` | An explicit metadata filter names a value the corpus does not use, removing every candidate | «برای فیلتری که مشخص شد هیچ مستندی وجود ندارد. این به معنای نبود پاسخ در مستندات نیست؛ مقدار فیلتر با مستندات ایندکس‌شده مطابقت ندارد.» | Read `filter_field` and `filter_values_present` in the log. Not a documentation gap — never report it as one |
| `INDEX_STALE` | Active index older than N days, or docs SHA moved | Answer served + freshness note | Trigger reindex |
| `RETRIEVAL_FAILED` | pgvector query error / DB unreachable | «مشکلی در جست‌وجوی مستندات پیش آمد. لطفاً دوباره تلاش کنید.» | Check Postgres |
| `EMBEDDING_FAILED` | Embedding call failed | same, with retry | Check AvalAI + gateway |
| `ALL_PROVIDERS_UNAVAILABLE` | Every provider down | «سرویس پاسخ‌گویی موقتاً در دسترس نیست. سؤال شما ذخیره شد.» | Check Portkey circuit state |
| `RATE_LIMITED` | Local rate limit hit | «تعداد درخواست‌ها زیاد است. لطفاً کمی صبر کنید.» | Expected |
| `NO_EVIDENCE` | Retrieval succeeded, evidence insufficient to answer | Agent abstains and says so explicitly | Feed to docs-gap analytics |
| `INGESTION_SOURCE_UNAVAILABLE` | Docs repo unreachable/unreadable, or scope matched no files | «دریافت مستندات از مخزن اصلی ممکن نشد، بنابراین ایندکس به‌روزرسانی نشد. پاسخ‌ها همچنان از آخرین نسخه‌ی سالم ارائه می‌شوند.» | Check `DOCS_REPO_URL`, `DOCS_REPO_BRANCH`, `INGEST_SECTIONS`; prior index untouched |
| `INDEX_VALIDATION_FAILED` | New index failed smoke validation and was not activated | «نسخه‌ی جدید ایندکس اعتبارسنجی نشد و فعال نشد. پاسخ‌ها از نسخه‌ی سالم قبلی ارائه می‌شوند.» | Read `index_versions.validation_report` for the failed check |
| `DOCUMENT_PARSE_FAILED` | MDX pre-pass produced no text for a non-empty source document | «یکی از صفحه‌های مستندات قابل پردازش نبود و ایندکس نشد. این یک خطای پردازش مستندات است، نه نبود پاسخ.» | Inspect that document's `discarded_char_ratio` and the unrecognized tags in the ingestion report; upstream likely added a component the §7 table misses |
| `FAQ_GENERATION_FAILED` | FAQ model/gateway call failed for a document | «تولید پرسش‌های مرتبط از مستندات ناموفق بود. پرسش‌های معتبر قبلی همچنان در دسترس‌اند.» | Check the FAQ request and gateway response |
| `FAQ_OUTPUT_INVALID` | One generated FAQ entry failed structured validation | «خروجی تولید پرسش‌های مرتبط ساختار معتبر نداشت و ذخیره نشد. سایر پرسش‌های معتبر پردازش شدند.» | Inspect recorded validation errors and source document |
| `HISTORY_LIMIT_REACHED` | A conversation passed `MAX_CONVERSATION_TURNS`. This is an abuse ceiling, not the ordinary end of a conversation — older turns are summarized, so a normal thread never reaches it | «این گفت‌وگو به سقف نوبت‌های مجاز رسیده و بسیار طولانی شده است. برای ادامه، پرسش بعدی را در یک گفت‌وگوی تازه بپرسید.» | Seeing it often means the ceiling is set too low or one session is looping |
| `SKILL_NOT_AVAILABLE` | The deployment artifact does not contain the configured Skill file | «فایل Skill در این استقرار در دسترس نیست.» | Check `SKILL_FILE_PATH` and deployment inclusion of `.agents/skills/liara-docs-rescue` |

`NO_ACTIVE_INDEX` (system broken) and `NO_RESULTS_ABOVE_THRESHOLD` (working correctly, real docs gap) must **never** share a message. One is an outage; the other is your product's most valuable data.

`NO_RESULTS_FOR_FILTER` was added after a third way of looking empty was found in the wild. Driving the Skill through a real coding agent, `runtime="node"` returned nothing — the corpus stores `nodejs`, derived from the documentation's own directory names, and a hard filter on a value it never uses removes every candidate. Reported as `NO_RESULTS_ABOVE_THRESHOLD`, the agent correctly followed the rule and confidently told the user the documentation had no answer. It did have the answer.

Two defenses now: `_RUNTIME_ALIASES` in `src/services/retrieval.py` normalizes the names callers actually type (`node`, `golang`, `.net`, `ts`), and anything still unmatched raises `NO_RESULTS_FOR_FILTER` naming the field and the values the index does hold. The check runs only when a search comes back empty, so the common path pays nothing for it.

**The lesson generalizes.** A hard filter is the one place in retrieval where being slightly wrong *removes* evidence rather than reordering it. Every future filter needs the same question asked of it: when this matches nothing, can the caller tell that apart from a documentation gap?

Codes appear in the API response, structured logs, and dashboard failure counts — the same string everywhere, so grepping a log and filtering the dashboard use identical vocabulary.

### Shutdown & rollback

Graceful shutdown on API and Worker: stop accepting work, drain in-flight jobs, close SSE connections cleanly so clients reconnect rather than hang.

**Index safety:** never mutate the active index in place. Write a new `index_version`, validate with smoke queries, flip activation atomically, retain the previous healthy version. A failed reindex must leave the running index untouched.

---

## 10b. Admin console

Behind HTTP Basic from `ADMIN_USERNAME` / `ADMIN_PASSWORD`, mounted under
`/api/v1/admin`. Unset credentials mean the surface refuses **everyone** — a
deployment that forgot the variables gets a locked door, not an open one.

The web console at `/admin` is a face on these same routes and adds no
authentication of its own. It holds the credentials **in memory only** — never
`localStorage`, never `sessionStorage` — so a reload asks again rather than
leaving an administrator's password on the disk of whatever browser was used.

| Route | Purpose |
|---|---|
| `GET /admin/faq` | Page and search the FAQ corpus; `embedded: false` marks an entry that cannot match |
| `PATCH /admin/faq/{id}` | Edit; re-embeds when the question changed |
| `DELETE /admin/faq/{id}` | Remove an entry from user-facing results |
| `GET/PUT/DELETE /admin/config/{key}` | Runtime tuning without a redeploy |
| `POST /admin/sync` → `GET /admin/sync` | Trigger an incremental reindex, then poll it |
| `GET /admin/dashboard` | Every figure, each with an explicit `no_data` flag |
| `GET /admin/feedback` | Individual verdicts with the answer each one judged, filterable by stage, outcome, and window |
| `GET /admin/index-versions` | Recent versions, so a rollback target is chosen by evidence |

**Runtime configuration** is an allowlist — `faq_similarity_threshold`,
`retrieval_similarity_threshold`, `faq_top_k`, `retrieval_top_k`, and
`faq_priority_weight`, stored in `runtime_settings` and validated against the
same bounds the environment is. Nothing there can reach a credential, an
endpoint, or a model id. An absent row means the deployed value stands, so the
table records only deliberate departures from the environment.

**`POST /admin/sync` answers 202, not 200.** The work is accepted, not finished:
a full rebuild takes minutes to an hour. One run at a time is enforced by a
Redis lock with a TTL, so two replicas cannot race to activate different index
versions and a killed process cannot wedge the system. A failure leaves the
previously active index serving, because activation is the last step and atomic.

**Every dashboard figure is a `Metric`** — a value with the event count behind
it, or an explicit `no_data`. There is no third state. Zero is a measurement
("no question failed"); absence is not, and a dashboard that renders them
identically shows a healthy 0% failure rate for a system that has been down
since deploy. Cost is reported only over events that actually carry one, so an
unpriced model is never presented as free.

**Answer-quality figures** come from chat-stage feedback, which is recorded per
answer and joined server-side to the documentation pages that answer cited:

| Metric | The question it answers |
|---|---|
| `chat_satisfaction_rate` | What share of generated answers the user judged helpful |
| `lowest_rated_pages` | Which documentation pages keep backing rejected answers — the actionable one |
| `feedback_reasons` | Whether the failures are "incomplete" (corpus), "irrelevant" (retrieval), or "incorrect" (grounding) |
| `top_questions` | What people actually ask, grouped on the normalized form, counted once per search |
| `top_cited_pages` | Which parts of the corpus the answers lean on; read against `lowest_rated_pages` |
| `questions_over_time` | Daily volume, with quiet days absent rather than zero-filled |
| `abstention_rate` | How often the system honestly declined; near zero on a corpus with known gaps means it is answering things it should not |
| `faq_hit_rate` | What share of searches returned anything above the threshold — the number to watch after moving one |

`faq_hit_rate` and `top_questions` need a row per *search*, including searches
that matched nothing. Impressions are written per shown entry and only when
something was shown, so the search itself is recorded server-side in
`POST /faq/search` with a `result_count` payload; those rows are what both
metrics count.

### Verified against production, 2026-08-21

Unauthenticated `GET /api/v1/admin/dashboard` returns 401 with a Persian body
and nothing else. Authenticated, it returned the no-data contract working
exactly as intended on a system with real data but no user traffic yet:

- `faq_resolution_rate`, `rescue_tool_split`, `unresolved_questions`,
  `unresolved_pages`, `failures_by_code`, `provider_fallbacks` — all
  `no_data: true`, `value: null`. Nobody has used the product yet, and the
  dashboard says so instead of reporting a flattering zero.
- `active_index` — `a60589fd`, commit `dbb7430`, 1,143 documents, 3,776 chunks.
- `faq_corpus` — 4,066 entries, all active, 0 awaiting re-embedding.
- `token_usage` — 1,417,916 tokens from the ingestion run, while `cost_usd` is
  `no_data`, because embeddings were recorded without a unit price. **This is
  the intended behavior**: an unpriced model reports absence rather than $0.00.

> **Alembic autogenerate will try to drop the HNSW indexes.** It cannot read a
> pgvector index — it sees no opclass it recognizes on either side and concludes
> the index is surplus. Applying that silently degrades every similarity query
> to a sequential scan: slower, still correct, nothing fails, nobody is paged.
> **Delete those `drop_index` lines from every autogenerated revision**, and
> verify after migrating that both indexes still exist.

---

## 11. Security checklist

- [ ] **Rotate the AvalAI key that was exposed during planning.**
- [ ] `.env` in `.gitignore`; production secrets only in the Liara panel
- [ ] Redact keys, cookies, and tokens in all log output
- [ ] Rate limit by IP and session (Redis)
- [ ] Cap question length and conversation history depth
- [ ] Admin panel behind HTTP Basic over HTTPS
- [ ] Retrieved doc content framed as **data, never instruction** — with an injection test in the suite
- [ ] Retrieval domain allowlist: Liara docs only
- [ ] Pin dependency and base-image versions

---

## 12b. Evaluation

Two tiers, deliberately. The generated tier gives coverage; the human tier gives something to trust when the generated tier is wrong.

```text
┌─ GOLDEN SET ── 10 questions, hand-written from the docs ────────────┐
│  Authored by a human against real pages. Highest trust.             │
│  → docs/eval/golden-set.md                                          │
│  → Regression gate: any drop here BLOCKS merge to main              │
│  → Also calibrates the judge: if the judge disagrees with a human    │
│    verdict here, the JUDGE is wrong, not the answer                 │
└──────────────────────────────────────────────────────────────────────┘
┌─ GENERATED SET ── ~20–50 questions, LLM-authored from chunks ───────┐
│  Cheap breadth across services, runtimes, difficulty bands.         │
│  Scored by LLM-as-judge. Directional signal, not a gate.            │
└──────────────────────────────────────────────────────────────────────┘
```

### The judge must not be the model under test

`EVAL_JUDGE_MODEL` **must differ from** `LLM_MODEL`. A model scoring its own output systematically prefers its own phrasing, structure, and mistakes — self-preference bias is well documented and it silently inflates every metric that matters.

Since AvalAI exposes many models, this costs nothing: generate with `gemini-3.7-flash`, judge with a different family. Judge calls are short (question + answer + expected points + retrieved sources in, a verdict out), so cost stays negligible.(GPT‑5.6 Luna might be good option for judge)

**Spot-check the judge itself.** Manually review ~10 judge verdicts on the golden set before trusting any aggregate number. An uncalibrated judge produces confident, precise, meaningless scores.

### What gets scored

| Metric | Source |
|---|---|
| Retrieval Recall@k | Deterministic — expected source pages vs. retrieved. **No judge needed.** |
| Citation correctness | Deterministic — do cited URLs exist in retrieved evidence? |
| Groundedness / unsupported claims | Judge |
| Answer relevance and completeness | Judge |
| Clarification correctness | Judge — did it ask only when it should have? |
| Abstention correctness | Judge — did it refuse when evidence was absent? |
| Latency, tokens, cost | Deterministic |

Prefer the deterministic metrics. Recall@k and citation correctness need no model at all, and they catch the failure mode that matters most — retrieval quality — with zero judge bias.

Record a baseline before tuning prompts or retrieval. No significant retrieval or prompt change merges without comparing against it.

---

## 12. Demo readiness

The recorded video is the primary judged artifact, so protect it:

- Pre-verify the scripted question (`FastAPI runs locally but won't start after deploying to Liara`) returns strong Related Questions **before** recording
- Pre-warm the cache along the demo path
- Rehearse the provider-fallback moment so it triggers on cue
- Keep one Playwright happy-path test as your own regression guard; the six failure scenarios drop to P2 — a judge never sees them
