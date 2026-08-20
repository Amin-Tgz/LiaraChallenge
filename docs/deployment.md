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
| Gateway | Portkey, **self-hosted** (single Node container) | decided |
| LLM observability | Opik, **hosted free tier** — self-host is out of scope | decided |
| Runtime telemetry | structured JSON logs + counters in Postgres. No OTel/Prometheus/Grafana in v1 | decided |
| Chat execution | Redis queue + Worker, SSE relay via Redis | decided |
| Web serving | React bundle served **from the API origin** (same-origin) | decided |
| Auth | Admin only — HTTP Basic from env. No end-user auth | decided |
| FAQ corpus | LLM-generated from docs, admin-curated, admin `sync` button | decided |
| Ingest scope | Config-driven section allowlist | decided |
| MCP | Kept, last-phase priority | decided |
| Persian normalization | Custom normalizer (ی/ي, ک/ك, ZWNJ, digits, spacing) | decided |
| FAQ threshold | **Cosine similarity**, admin-editable, default 0.4 | decided |

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

**Five services, ~5 GB total.**

| Service | Plan | Rationale |
|---|---|---|
| PostgreSQL | **2 GB** | 12k chunks × 1536 dims ≈ 74 MB of vectors + ~150 MB HNSW index. 1 GB works until the index build; 2 GB gives `maintenance_work_mem` headroom. The only service worth paying up for. |
| Redis | 0.5 GB | Queue, cache, rate limits, SSE relay. Data footprint is trivial. |
| API + Web | 1 GB | uvicorn plus concurrently-held SSE connections. |
| Worker | 1 GB | Ingestion peak. Stream files — never load all 1,142 at once. |
| Portkey | 0.5 GB | Single Node container. |

### Why Web is merged into the API

Two problems solved by one decision:

1. **Cookies.** Separate subdomains would force `SameSite=None; Secure` plus credentialed CORS, fighting the "CORS محدود" requirement. Same-origin means `SameSite=Lax` and zero config.
2. **Cost + one less deploy target.**

FastAPI mounts the Vite build output as static files with an SPA catch-all. API routes live under `/api/v1` and never collide.

---

## 4. Liara provisioning

Do these **before** day 1 — the pgvector toggle restarts the database, so enable it while the DB is empty.

1. **PostgreSQL**, 2 GB. In the panel → تنظیمات افزونه → enable **Pgvector** → ثبت تغییرات. Accept the restart.
2. Verify version — `halfvec` needs ≥ 0.7.0, though the 1536-dim path doesn't depend on it:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   SELECT extversion FROM pg_extension WHERE extname = 'vector';
   ```
3. Check the lexical fallback:
   ```sql
   SELECT * FROM pg_available_extensions WHERE name = 'pg_trgm';
   ```
4. **Redis**, 0.5 GB.
5. Three app services: `api`, `worker`, `portkey`.
6. Set all env vars via the Liara panel's secrets UI. **Never deploy a `.env` file.**

---

## 5. Configuration

`.env` is for local development only and must be listed in `.gitignore`. Production values live in Liara secrets.

```env
# --- Chat LLM ---
LLM_BASE_URL=https://api.avalai.ir/v1
LLM_API_KEY=<from-liara-secrets>
LLM_MODEL=gemini-3.7-flash

# --- Bulk FAQ generation: separate var so it can diverge from chat ---
FAQ_LLM_MODEL=gemini-3.7-flash

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

# --- Retrieval ---
FAQ_SIMILARITY_THRESHOLD=0.4   # cosine SIMILARITY, not pgvector distance
FAQ_TOP_K=5
RETRIEVAL_TOP_K=8
RRF_K=60

# --- Agent bounds ---
AGENT_MAX_TOOL_CALLS=3
AGENT_MAX_REWRITES=2
AGENT_TOKEN_BUDGET=8000
AGENT_TIMEOUT_SECONDS=60

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

## 7. MDX pre-pass

Content is Next.js Pages Router + `@next/mdx` v3. Every file wraps content in `<Layout>` and imports custom components.

> **Critical:** section headings are **not** Markdown. They are `<Section id="…" title="…" />` JSX components. A Markdown-only parser sees one undifferentiated blob per file and chunking silently collapses.
>
> The upside: `id` and `title` are explicit, so `heading_anchor` and `section` metadata come free and citations deep-link as `{source_url}#{id}`.

Two stages: a JSX pre-pass producing clean Markdown, then `mistune` in AST mode (`create_markdown(renderer=None)`) for section-aware chunking.

| Source construct | Transform |
|---|---|
| `import …` / `export …` | drop |
| `<Layout>` wrapper, `<Head>…</Head>` | unwrap; drop head |
| `<Section id="X" title="Y" />` | `## Y` + record anchor `X` |
| `<Step number="…">…</Step>` | keep content, mark as step (stays in one chunk with its image) |
| `<Tabs>` | flatten, one block per tab label |
| `<Alert>` `<Important>` `<Highlight>` | keep inner text as blockquote |
| `<Card>` `<Button>` `<PlatformIcon>` | drop — navigation only |
| `{ … }` JS expression blocks | drop |
| `<a href="X" className="…">Y</a>` | `[Y](X)` — **keep the link**, drop the styling |
| `<div>` `<b>` `<hr className=…>` | strip tag, keep text |

> **Match on the JSX tag name, never the import path.** Verified across three files: `paas/about.mdx` imports `Tabs` from `@/components/Common/tabs` while `paas/django/getting-started.mdx` imports it from `@/components/Common/tab` (singular). The repo is internally inconsistent. Tag names are stable; import paths are not.

**Guardrail metric.** Log the percentage of characters discarded per file. Liara owns this repo and can add components at any time; without this metric a new component degrades retrieval silently. Alert above a threshold. Assert in tests that no `<` or `{` survives into embedded text.

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

**Wall-clock, not cost, is the real constraint.** Full-corpus FAQ generation is ~1,142 requests; at RPM 10,000 with ~20-way concurrency that is **15–25 minutes** unattended. Embeddings finish in 1–2 minutes.

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

Each deploy: build immutable versioned image → run migrations → deploy → poll `/health/ready` → roll back on failure.

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
| `INDEX_STALE` | Active index older than N days, or docs SHA moved | Answer served + freshness note | Trigger reindex |
| `RETRIEVAL_FAILED` | pgvector query error / DB unreachable | «مشکلی در جست‌وجوی مستندات پیش آمد. لطفاً دوباره تلاش کنید.» | Check Postgres |
| `EMBEDDING_FAILED` | Embedding call failed | same, with retry | Check AvalAI + gateway |
| `ALL_PROVIDERS_UNAVAILABLE` | Every provider down | «سرویس پاسخ‌گویی موقتاً در دسترس نیست. سؤال شما ذخیره شد.» | Check Portkey circuit state |
| `RATE_LIMITED` | Local rate limit hit | «تعداد درخواست‌ها زیاد است. لطفاً کمی صبر کنید.» | Expected |
| `NO_EVIDENCE` | Retrieval succeeded, evidence insufficient to answer | Agent abstains and says so explicitly | Feed to docs-gap analytics |

`NO_ACTIVE_INDEX` (system broken) and `NO_RESULTS_ABOVE_THRESHOLD` (working correctly, real docs gap) must **never** share a message. One is an outage; the other is your product's most valuable data.

Codes appear in the API response, structured logs, and dashboard failure counts — the same string everywhere, so grepping a log and filtering the dashboard use identical vocabulary.

### Shutdown & rollback

Graceful shutdown on API and Worker: stop accepting work, drain in-flight jobs, close SSE connections cleanly so clients reconnect rather than hang.

**Index safety:** never mutate the active index in place. Write a new `index_version`, validate with smoke queries, flip activation atomically, retain the previous healthy version. A failed reindex must leave the running index untouched.

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
