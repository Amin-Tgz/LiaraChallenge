## Context

Greenfield repository — only specification documents exist. See `proposal.md` for motivation.

Infrastructure decisions (service topology, resource sizing, models, pricing, environment configuration, MDX transform table, error taxonomy, provisioning steps) are already settled in `docs/deployment.md` and are not restated here. This document covers the architectural choices that document does not make.

Three constraints shape everything below:

1. **Two days, one developer.** Feature breadth is fixed; depth varies. Every decision favors the option that reaches a demonstrable state soonest and can be deepened later without rework.
2. **The upstream corpus is not ours.** `liara-cloud/docs` can change its component set at any time, so parsing must degrade measurably rather than silently.
3. **Answer quality is the dominant judged criterion.** Where a choice trades operational elegance against retrieval or answer quality, quality wins.

## Goals / Non-Goals

**Goals:**

- A single retrieval core serving web chat, MCP, and the Skill identically, so the citation contract cannot drift between surfaces.
- Chunking that survives a corpus whose section headings are JSX props rather than Markdown.
- Durable request handling where reload, disconnect, and worker restart are ordinary rather than exceptional.
- Failure paths that are distinguishable by construction, not by log archaeology.

**Non-Goals:**

- Horizontal scale. Single instance per service; no distributed coordination beyond Redis.
- A general agent framework. The agent is a bounded loop over three tools.
- Multi-tenancy or end-user identity.
- Optimizing inference cost. Total spend is under $20; latency and quality are the real budgets.

## Decisions

### Two-stage MDX parsing rather than a true MDX parser

The corpus is MDX with custom components, and crucially stores section titles as `<Section id title />` props. Python has no production-grade MDX parser, and section structure is what chunking depends on.

**Chosen:** a JSX pre-pass producing clean Markdown, then `mistune` in AST mode (`create_markdown(renderer=None)`) for structure. The pre-pass matches on tag names, never import paths — verified necessary, since the repo imports `Tabs` from both `Common/tab` and `Common/tabs`.

*Alternatives:* running a Node `remark` subprocess (accurate but adds a runtime dependency and cross-process failure modes for marginal gain); regex-only extraction (no reliable heading hierarchy or code-fence handling).

*Consequence:* the pre-pass encodes assumptions about a repo we don't control, so it emits a discarded-character ratio per file. A new upstream component shows up as a metric change instead of silent retrieval decay.

### Chunk at `<Section>` boundaries, with the anchor as the citation key

Sections are the natural semantic unit and each carries an explicit `id`. Citations become `{source_url}#{id}` with no inference. Sub-splitting only when a section exceeds the token target; merging when below the floor. Code blocks and their adjacent prose, and steps with their images, are never split.

### One retrieval core, three surfaces

Web chat, MCP tools, and the Skill's guidance all resolve to the same search function. The spec requires consistent citations across surfaces; sharing the implementation makes that structural rather than a thing to remember.

### RRF over score normalization for fusion

Dense and lexical scores are not on comparable scales, and tuning a normalization is a research task. Reciprocal Rank Fusion needs only ranks, has one parameter, and is explainable when a result looks wrong. Contributing per-method ranks are retained so ordering can be justified during evaluation.

*Trade-off:* discards score magnitude. Acceptable — with a corpus this small, precision at the top of the list matters more than calibration.

### Lexical retrieval on normalized text via `tsvector`

Persian has no built-in Postgres text search configuration. Normalized text indexed with the `simple` configuration handles the highest-value lexical cases — error messages, commands, service names — which are Latin. `pg_trgm` improves fuzzy Persian matching but is not confirmed available on Liara, so it is an enhancement, not a dependency.

**The normalizer is the single highest-risk small component.** It must be applied byte-identically at index time and query time; asymmetry causes silent recall loss with no error. It is pure, unit-tested against fixed cases, and versioned — a change to it invalidates the lexical index and forces a reindex.

### FAQ as a separate embedding space

FAQ matching compares a question against *questions*, not against document chunks. Question-to-question similarity is better behaved than question-to-passage, and it keeps the fast path independent of chunking changes. Cost is negligible (~5,700 short questions).

### Generate in the worker, relay through Redis Streams

The spec requires both streamed answers and jobs that survive client disconnection. Those pull in opposite directions: streaming wants the generating process to own the connection; durability wants generation off the request path.

**Chosen:** the worker generates and appends tokens to a per-job Redis Stream; the API's SSE endpoint tails that stream. Reconnection replays from the last delivered offset, which is what makes resume correct rather than approximate. Completed answers persist to Postgres; the stream is ephemeral.

*Alternative:* generating in the API process. Simpler, but loses work on disconnect and on any API restart.

**This is the highest-complexity item in the build.** In-process generation is the pre-planned fallback if it threatens the day-1 schedule — the interface between the chat service and its transport is kept narrow specifically so that substitution stays a small change.

**Implemented, with one correction to the above.** The relay carries *validated answer text*, not raw model tokens. The bounded agent's final turn is a structured JSON response whose `citation_ids` must be resolved against retrieved evidence before any of it is shown; forwarding the model's raw token stream would put unvalidated and possibly uncited text on screen, which the grounding rule in `RULES.md` §1 forbids, and would stream JSON syntax rather than prose. The worker therefore validates first, then appends the finished answer to the stream in `JOB_STREAM_CHUNK_CHARS`-sized entries. Everything the spec actually requires of the relay — offsets, resumption from `Last-Event-ID`, survival of client disconnection, no regeneration on reload — holds unchanged; what a client sees is progressive delivery of a checked answer rather than live decoding. The gateway is non-streaming today, so this costs no latency that streaming would have saved.

Durability is lease-based rather than acknowledgement-based: a worker `SET NX EX`s a lease key while it works and refreshes it on a heartbeat. A worker that is killed does not have to run any cleanup — its lease simply stops being renewed, and `reclaim_orphaned_jobs` returns any non-terminal job with no lease and no queue entry to the queue on the next worker start. Jobs are persisted before they are enqueued, so a crash between the two leaves a visible row rather than a lost question.

### Idempotency at the job layer

Each submission carries a client-generated key; a unique constraint on it makes duplicate submission a no-op returning the existing job. This is what makes reload-during-generation safe, and it is cheaper and more reliable than deduplicating in the client.

### Native function calling for the agent loop

The chat model supports function calling and structured output, so tools are declared natively rather than emulated through prompt formatting and output parsing. The loop is explicit — call model, execute any requested allowlisted tool, append result, repeat — with hard counters for tool calls and rewrites, a token budget, and a wall-clock timeout. Bounds are enforced in the loop, not requested in the prompt, because a prompt-level limit is a suggestion.

Structured output is also used for bulk FAQ generation, removing a class of parse-failure retries.

### Session profile as a JSON column, updated per turn

The technical profile (service, runtime, framework, experience, goal, deployment mode, known error) lives as JSON on the conversation. Schema-free, requires no migration as fields evolve, and is read whole on every turn anyway. Populated from explicit user statements and clarification answers.

### Error codes as a shared enum, surfaced everywhere

The taxonomy in `docs/deployment.md` §10 is implemented as one enumeration used by API responses, log records, and dashboard aggregation. Every raise site selects a member; no free-text failure messages reach a user. This is what makes `NO_ACTIVE_INDEX` and `NO_RESULTS_ABOVE_THRESHOLD` structurally impossible to conflate — the requirement the whole taxonomy exists to enforce.

Readiness composes the same checks, so "why is it not ready" and "why did that request fail" share vocabulary.

### Index versioning by row tagging, not table swapping

Chunks carry an `index_version`; activation flips a pointer row. Retrieval always filters by the active version. Rollback reactivates a prior version; retention keeps the last two. Cheaper than table swapping or a separate index store, and makes atomic activation a single-row update.

### Two environments, one set of images

There is no self-hosted tier. Local development runs the whole stack on Docker Desktop via `docker compose`; production runs the same services on Liara, with Postgres and Redis as Liara-managed instances. The Portkey gateway, Prometheus, Grafana, Loki, and Grafana Alloy are project-owned containers in both environments. Monitoring storage is persistent and telemetry delivery stays off the user request path. Opik is the only external SaaS: nothing is deployed for it and both environments call the same endpoint.

Keeping `docker compose up` sufficient to run everything locally is what keeps the dev/prod gap small enough that "works locally" means something.

### Alembic owns every schema change

Migrations are generated and applied through Alembic, with `alembic/env.py` reading the database URL from settings so both environments share one migration path. No `create_all` in application code, no hand-written DDL. Deployment applies migrations as an explicit controlled step rather than on application startup, so a failed migration is a failed deploy rather than a half-migrated running service.

Broader backend layout — adopted selectively from the FastAPI Starter Kit reference, and what was deliberately left out — is in `docs/deployment.md` §6b.

### Serve the built frontend from the API origin

Removes cross-site cookie configuration, credentialed CORS, and one deploy target simultaneously. API routes are namespaced under `/api/v1`; everything else falls through to the SPA. The trade-off — frontend and backend deploy together — is a benefit at this scale.

## Risks / Trade-offs

**Upstream component drift breaks parsing silently** → Tag-name matching plus a per-file discarded-character metric with a threshold alert; assertions that no JSX survives into embedded text.

**Persian normalizer asymmetry causes invisible recall loss** → One pure function used by both paths, unit-tested on fixed cases, versioned so a change forces reindex.

**Worker-to-SSE relay overruns the schedule** → Narrow transport interface; in-process generation as a pre-planned substitution.

**Retrieval quality on Persian questions is unproven** → The 10-question human-authored golden set gates merges; Recall@k and citation correctness are computed deterministically with no judge involved.

**LLM-as-judge inflates scores** → Judge model must differ from the model under test; judge verdicts spot-checked against human verdicts on the golden set before any aggregate is trusted.

**Large English sub-trees skew retrieval on Persian questions** → Monitor their share of top-k during evaluation; ingest scope is configuration, so they can be excluded without code change.

**Two-day schedule leaves no slack** → Deployment happens in hour one, not at the end. Depth tiers are declared in advance so degradation is a decision rather than a surprise. Ingest scope is the pressure valve.

**The gateway becomes a single point of failure** → It is a stateless container; if it fails to come up, the application can address the primary provider directly, losing fallback but not service.

## Migration Plan

No migration — greenfield. Deployment sequence:

1. Provision Postgres (with the pgvector extension enabled before data exists, since enabling it restarts the database), Redis, and the application services.
2. Deploy a walking skeleton and confirm readiness reports every dependency. **Hour one.**
3. Apply schema migrations.
4. Run ingestion; confirm an active index version exists and readiness turns positive.
5. Generate the FAQ set; review in the admin console.
6. Deploy subsequent releases only after CI passes, verifying readiness after each and rolling back on failure.

Rollback: redeploy the prior image. Index rollback is independent — reactivating a prior index version does not require redeployment, and a failed ingestion never disturbs the active index.

## Open Questions

- ~~Whether `pg_trgm` is available on Liara's managed Postgres.~~ **Answered 2026-08-21:** a read-only query through the external Liara connection confirmed `pg_trgm` is available and installed at version 1.6. The same check confirmed `vector` is installed at version 0.8.1. Fuzzy Persian lexical matching may therefore use `pg_trgm`; `tsvector` remains the baseline retrieval path.
- Which secondary provider to configure for fallback. The gateway makes this configuration; the requirement is only that one exists and is reachable from the deployment network.
- ~~Final chunk count and the resulting HNSW build parameters — measurable only after the first full ingestion run.~~ **Answered.** The first full run at upstream commit `dbb7430` produced **3,776 chunks** across 1,143 documents (11 sections; `tv` contains no `.mdx`), token range 120–1,149, 376 images. Default HNSW parameters (`m=16`, `ef_construction=64`) are adequate: at this size the planner actually prefers a sequential scan, and a forced index scan is no faster — 13.3 ms against 14.4 ms median for top-8 similarity. The index earns its place as the corpus grows, not today. Revisit only if chunk count grows by an order of magnitude.
