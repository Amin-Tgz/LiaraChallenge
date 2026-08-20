## Why

Liara users regularly fail to find answers that already exist in the documentation — they don't know which service or runtime their question belongs to, their vocabulary differs from the docs', the answer is spread across several pages, or it depends on a panel screenshot. A plain chatbot is the wrong answer: it costs inference on every question and can fabricate. Users need to be routed to the cheapest reliable path first, and escalated only when that path fails.

This change builds the v1 competition deliverable: a documentation rescue system that funnels a single question through FAQ → self-serve agent tooling → bounded Agentic RAG chat, keeping question and state intact across every hop, and turning real failures into documentation-gap data.

Implements plan sections §6 (core UX), §7.1 (P0 scope), §11–§14 (ingestion, images, retrieval, bounded agent), §16–§19 (MCP, Skill, state, resilience), §20–§22 (security, observability, dashboard), §26 (evaluation), §31 (Definition of Done).

## What Changes

Greenfield — the repository currently contains only specification documents. Everything below is new.

- **Documentation ingestion** — clone `liara-cloud/docs`, run a JSX pre-pass that converts `<Section id title />` components into real headings (they are *not* Markdown), chunk by section, extract metadata and images, embed at 1536 dimensions, and activate versioned indexes atomically with rollback.
- **Hybrid retrieval** — dense pgvector search fused with lexical search over Persian-normalized text via RRF, returning scored chunks with deep-linkable citations (`source_url#anchor`).
- **FAQ fast path** — LLM-generated, admin-curated question/answer pairs matched by embedding similarity against a configurable threshold, with solved/unresolved feedback captured for analytics.
- **Rescue flow** — landing page, related questions, feedback, and the three rescue tools (Skill / MCP / Chat), with the original question and conversation surviving refresh and tab reopen.
- **Bounded Agentic RAG chat** — allowlisted tools only, capped tool calls and rewrites, enforced token budget and timeout, clarification only when it changes the answer, mandatory citations, and explicit abstention when evidence is insufficient. Streamed over SSE from a queued worker.
- **Agent integrations** — an installable Skill teaching a coding agent the rescue workflow, and an MCP server exposing the same retrieval with strict schemas.
- **Admin console** — HTTP Basic auth, FAQ generation and CRUD, threshold configuration, an incremental sync trigger, and a dashboard covering solved rate, tool split, unresolved questions, cost, and index state.
- **Platform operations** — per-dependency readiness reporting, a distinct-cause error taxonomy, rate limiting, provider fallback through a Portkey gateway we run as our own container, structured logging, Alembic-managed migrations, and deployment to Liara.
- **Evaluation** — a human-authored 10-question golden set as the regression gate, plus LLM-as-judge scoring where the judge is a different model family than the one under test.

No breaking changes — there is no existing behavior.

## Capabilities

### New Capabilities

- `docs-ingestion`: Fetching Liara's documentation repository, JSX pre-pass and Markdown parsing, section-aware chunking, metadata and image extraction, batch embedding, and versioned index activation with rollback.
- `docs-retrieval`: Persian text normalization, dense and lexical retrieval, RRF fusion, evidence selection, and citation construction with deep-link anchors.
- `faq-fast-path`: FAQ generation from indexed documents, semantic matching against a configurable similarity threshold, curated ordering, and solved/unresolved feedback capture.
- `rescue-flow`: The user journey from landing through related questions, feedback, and rescue-tool selection — including question persistence, navigation between tools, and RTL/LTR rendering.
- `chat-agent`: Bounded Agentic RAG — allowlisted tools, enforced limits, clarification behavior, session technical profile, streaming delivery, conversation durability, and abstention.
- `agent-integrations`: The installable Skill and the MCP server — tool schemas, citation and image output contracts, installation configuration, and rate limiting.
- `admin-console`: Admin authentication, FAQ management, runtime configuration, index sync triggering, and the analytics dashboard.
- `platform-operations`: Health and readiness semantics, the error taxonomy, rate limiting, provider resilience and fallback, structured logging with correlation IDs, and deployment and rollback behavior.

### Modified Capabilities

None — no existing specs.

## Impact

**New systems.** Five services, deployed on Liara in production and run locally via Docker Desktop and `docker compose` during development: API (serving the React bundle same-origin), Worker, PostgreSQL with pgvector, Redis, and the Portkey gateway as our own container image rather than Portkey's managed SaaS. Roughly 5 GB total. Nothing is self-hosted on administered hardware.

**External dependencies.** AvalAI for `gemini-3.7-flash` and `text-embedding-3-large`; a secondary OpenAI-compatible provider for fallback; Opik SaaS for LLM tracing — the only dependency that is neither deployed nor containerized; `liara-cloud/docs` as an upstream content source the project does not own.

**Data.** Eleven tables covering sessions, conversations, messages, jobs, feedback, FAQ items, documents, chunks, index versions, image assets, and usage events. Embeddings are `vector(1536)` with HNSW.

**Constraints carried from planning.** Embeddings must be 1536-dimensional — pgvector caps HNSW indexes at 2000 dimensions, so the model's native 3072 cannot be indexed. Similarity, never distance, is the unit exposed in config, API, and logs. Ingest scope is configuration, not code, so breadth can be narrowed under time pressure without refactoring.

**Budget.** Approximately $4.25 one-time indexing and ~$0.005 per query; under $20 total. Wall-clock, not cost, is the binding constraint.

**Out of scope.** End-user authentication, Kubernetes, running Opik ourselves, multiple vector databases, unbounded agents, captioning every image, and auto-merging documentation fixes.
