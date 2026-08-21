## 1. Pre-flight verification

- [ ] 1.1 Rotate the AvalAI API key exposed during planning and verify the old key returns 401
  - **Blocked on rotation, not on verification.** Checked 2026-08-21: the exposed key
    still authenticates — `scripts/verify_providers.py` reports HTTP 200 from
    `api.avalai.ir`, so it remains live and usable by anyone holding it. The operator
    was informed and chose to defer. Once rotated, this task passes by running
    `uv run python -m scripts.verify_providers --expect-unauthorized OLD_AVALAI_KEY`
    with the old value in that environment variable; it passes only on a 401.
- [x] 1.2 Create Postgres via `liara db:create` per docs/deployment.md §4; verify it appears in `liara db:list` with status OK
- [x] 1.3 **Manual step — the CLI cannot do this.** Enable Pgvector in the Liara panel before any data exists, accept the restart, then verify `SELECT extversion FROM pg_extension WHERE extname='vector'` returns a version
- [x] 1.4 Check `pg_trgm` availability via `pg_available_extensions` and record the result in design.md Open Questions
- [x] 1.5 Create Redis and the `liara-rescue-api`, `-worker`, and `-gateway` app services per docs/deployment.md §4; verify each appears in `liara app:list` and shares a private network with the database
- [x] 1.6 Confirm the fallback provider is reachable **from a deployed container** (not a local machine) and record the working base URL

## 2. Walking skeleton deployed (hour one)

- [x] 2.1 Scaffold the FastAPI project per the layout in docs/deployment.md §6b with uv, `pyproject.toml`, `.python-version`, and a committed `uv.lock`; verify `uv sync --frozen` succeeds from a clean checkout
- [x] 2.2 Scaffold the React/TypeScript/Vite frontend; verify `npm run build` produces a bundle
- [x] 2.2b Write `docker-compose.yml` bringing up Postgres, Redis, API, Worker, and the Portkey gateway locally; verify `docker compose up` starts the full stack on Docker Desktop and `/health/ready` responds
- [x] 2.2c Initialize Alembic with `env.py` reading the database URL from settings; verify `alembic upgrade head` runs against both the local compose database and Liara
- [x] 2.3 Mount the built frontend as static files from the API with an SPA catch-all, API routes under `/api/v1`; verify the root path serves the SPA and `/api/v1/*` does not collide
- [x] 2.4 Add `.env.example` and confirm `.env` is gitignored; verify no secret appears in `git ls-files`
- [x] 2.5 Implement `/health/live` and a `/health/ready` returning per-dependency status; verify the response shape matches docs/deployment.md §10
- [x] 2.6 **Deploy to Liara and verify `/health/ready` is reachable over HTTPS with Postgres and Redis both reporting healthy**

## 3. Data model

- [x] 3.1 Define schema for sessions, conversations, messages, request_jobs, feedback, faq_items, documents, document_chunks, index_versions, image_assets, usage_events; verify Alembic generates and applies the migration
- [x] 3.2 Add `vector(1536)` column and HNSW index on document_chunks; verify `EXPLAIN` on a similarity query shows index usage rather than a sequential scan
- [x] 3.3 Add a unique constraint on the job idempotency key; verify duplicate insert raises rather than creating a second row
- [x] 3.4 Implement the error-code enumeration from docs/deployment.md §10; verify every member has a distinct code and Persian message via a table-driven test

## 4. Persian normalization

- [x] 4.1 Implement the normalizer (ی/ي, ک/ك, ZWNJ, digit forms, spacing) as a single pure versioned function; verify unit tests cover each transformation class
- [x] 4.2 Assert the same function is used at index time and query time; verify a test fails if either path bypasses it

## 5. MDX pre-pass and chunking

- [x] 5.1 Implement the JSX pre-pass per the transform table in docs/deployment.md §7, matching on tag names not import paths; verify `<Section id title />` becomes a heading carrying its anchor
- [x] 5.2 Verify against fixtures from at least 5 real documents across different sections that no `<` or `{` survives into embedded text
- [x] 5.3 Emit a discarded-character ratio per file and flag files above threshold; verify the metric appears in ingestion output
- [x] 5.4 Parse cleaned Markdown to AST with mistune and implement section-aware chunking; verify code blocks stay with adjacent prose and steps stay with their images
- [x] 5.5 Extract chunk metadata including source URL, heading anchor, breadcrumbs, service/runtime/framework, and images; verify a citation resolves to `{source_url}#{anchor}` for a known document
- [x] 5.6 Merge undersized chunks and split oversized ones against configured bounds; verify no stored chunk falls outside them

## 6. Ingestion pipeline

- [x] 6.1 Clone the docs repository at the configured branch and record the commit SHA; verify the SHA is stored on the index version
- [x] 6.2 Apply the configured section allowlist and exclude globs; verify narrowing the config excludes those documents without code change
- [x] 6.3 Detect added, modified, and deleted files against the active index; verify a no-change run exits without generating embeddings
- [x] 6.4 Generate embeddings in batches at 1536 dimensions via the gateway; verify the returned vector length is 1536 and the dimension is recorded on the index version
- [x] 6.5 Implement index version creation, smoke validation, and atomic activation with retention of the previous version; verify a failed validation leaves the prior index active
- [x] 6.6 Implement index rollback to a prior version; verify reactivation works without re-running ingestion
- [x] 6.7 **Run full ingestion against the real corpus and verify an active index exists and `/health/ready` turns positive**

## 7. Retrieval

- [x] 7.1 Implement dense retrieval over pgvector filtered by active index version; verify results carry score, text, metadata, source URL, anchor, and commit
- [x] 7.2 Implement lexical retrieval over normalized text with tsvector; verify an exact error string and a command name are both found
- [x] 7.3 Implement RRF fusion retaining per-method ranks; verify ordering is reproducible and contributing ranks are recoverable
- [x] 7.4 Expose relevance as similarity everywhere in config, responses, and logs; verify no distance value is returned where similarity is expected
- [x] 7.5 Implement metadata soft boosting with hard filtering only on explicit intent; verify a boosted query still returns non-matching chunks
- [x] 7.6 Distinguish no-active-index, retrieval-failure, and nothing-above-threshold; verify each returns its own error code and message

## 8. FAQ fast path

- [x] 8.1 Implement FAQ generation from indexed documents using structured output and `reasoning_effort=low`; verify malformed entries are rejected and recorded without aborting the run
- [x] 8.2 Embed FAQ questions into their own space and implement threshold matching; verify below-threshold results are suppressed
- [x] 8.3 Implement the synchronous FAQ search endpoint; verify no answer-generation model call occurs on this path
- [x] 8.4 Implement solved/unresolved feedback persistence and unresolved-question recording; verify both outcomes are queryable afterwards
- [x] 8.5 Record impressions, selections, and transitions to each rescue tool; verify events appear in usage_events
- [x] 8.6 **Run FAQ generation across the corpus and verify entries exist with correct source attribution**

## 9. Chat agent

- [x] 9.1 Implement the gateway client with primary and fallback providers; verify a simulated primary failure falls back and records the occurrence
- [x] 9.2 Declare the three allowlisted tools using native function calling; verify no other capability is reachable from the loop
- [x] 9.3 Implement the bounded agent loop enforcing tool-call, rewrite, token, and timeout limits in code; verify each limit terminates the turn under test
- [x] 9.4 Implement mandatory citation and abstention on insufficient evidence; verify an unanswerable question abstains with the no-evidence code rather than answering
- [x] 9.5 Implement clarification triggered only when the missing detail changes the answer; verify an under-specified but answer-invariant question is answered without asking
- [x] 9.6 Implement the session technical profile as JSON on the conversation, updated per turn; verify a runtime stated once is reused in a later turn
- [x] 9.7 Frame retrieved content as data not instruction; verify a prompt-injection fixture in retrieved content does not alter behavior

## 10. Queue, streaming, durability

- [x] 10.1 Implement job persistence before enqueue with the state machine queued → retrieving → generating → retrying → completed/failed; verify transitions are recorded
- [x] 10.2 Implement Redis queue and worker consumption with bounded retries and a terminal failed state; verify exhausted retries stop rather than loop
- [x] 10.3 Implement the Redis Streams token relay from worker to API; verify tokens produced in the worker reach an SSE client
- [x] 10.4 Implement SSE streaming with reconnection from last delivered offset; verify a client reconnecting mid-stream receives missed content and continues
- [x] 10.5 Verify idempotency: resubmitting the same key creates no second job and both submissions observe the same result
- [x] 10.6 Verify durability: killing the worker mid-generation resumes or safely retries without losing the question
- [x] 10.7 Implement graceful shutdown draining in-flight jobs and closing SSE cleanly; verify clients reconnect rather than hang

## 11. Rescue flow frontend

- [x] 11.1 Implement the landing view with a multi-line question input and immediate server-side persistence; verify the conversation row exists before retrieval starts
- [x] 11.2 Issue an anonymous session cookie and associate conversations; verify a reopened tab restores prior conversations
- [x] 11.3 Implement the related-questions view labeled as related questions, with solved/unresolved actions; verify below-threshold results show the not-found state and offer rescue tools
- [x] 11.4 Implement the rescue-tools view with plain-language descriptions of Skill, MCP, and Chat; verify moving between tools preserves the original question
- [x] 11.5 Implement chat view with streaming, Markdown, syntax-highlighted code blocks, per-block copy, links, and citations showing page title and section; verify each renders correctly
- [x] 11.6 Render associated images beside their step or citation with alt-text fallback; verify a broken image URL leaves the answer intact
- [x] 11.7 Implement RTL layout with LTR code blocks and correct mixed Persian/Latin inline rendering; verify against fixtures containing both
- [x] 11.8 Surface queued, retrieving, generating, retrying, completed, and failed states in plain language; verify failures state their cause rather than a generic message
- [x] 11.9 Verify reload during generation restores conversation and job status without restarting generation
- [x] 11.10 Verify keyboard navigation, visible focus states, semantic labels, contrast, and mobile and desktop viewports

## 12. Skill

- [x] 12.1 Author the Skill encoding the workflow from the agent-integrations spec; verify it instructs retrieval before answering and abstention without evidence
- [x] 12.2 Add installation instructions, a version identifier, and a worked example; verify the example runs against the deployed service
- [x] 12.3 **Verify the Skill end to end inside at least one real coding agent**
  - Verified 2026-08-21 by driving a coding agent through the Skill against the deployed
    service. It retrieved before answering, produced a fully grounded Persian answer citing
    `use-cdn` (0.712), `add-domain` (0.666), and `enable-ssl#use-ssl` (0.646) at commit
    `dbb7430`, and on the second question abstained with `NO_RESULTS_ABOVE_THRESHOLD`
    rather than reconstructing a fix from memory. Fifteen tool calls across all three tools.
  - **Caveat, recorded rather than smoothed over:** the agent reached the tools over raw
    JSON-RPC because the registered MCP server was not exposed to its session — MCP servers
    load at session start. That is a harness limitation, not a product one; the server
    answered `initialize` normally throughout. Native tool-call transport is exercised by
    `tests/integration/test_mcp_endpoint.py` and by `claude mcp list`.
  - The run produced six findings. The most serious is fixed: `runtime="node"` matched
    nothing and reported it as a documentation gap. See `NO_RESULTS_FOR_FILTER` in
    docs/deployment.md §10. The rest became guidance in SKILL.md, plus three open retrieval
    issues recorded under §19 below.

## 13. Admin console and dashboard

- [ ] 13.1 Implement HTTP Basic auth from environment credentials; verify unauthenticated requests are refused and disclose nothing
- [ ] 13.2 Implement FAQ review, edit, and delete with re-embedding on question change; verify a deleted entry stops appearing in user results
- [ ] 13.3 Implement the incremental sync trigger; verify a no-change run reports no change and a failed run leaves the active index untouched
- [ ] 13.4 Implement runtime configuration of the similarity threshold; verify a change affects subsequent matching without redeployment
- [ ] 13.5 Implement the dashboard covering FAQ resolution rate, tool split, unresolved questions and their pages, failures by error code, token usage and cost, fallback count, and index version and commit; verify every figure derives from recorded events
- [ ] 13.6 Verify metrics with no recorded events display an explicit no-data state rather than a fabricated value

## 14. Platform operations

- [x] 14.1 Implement rate limiting by IP and session in Redis; verify exceeding the limit returns the rate-limited code
- [x] 14.2 Enforce maximum question length and history depth; verify oversized input is rejected with a message stating the limit
- [ ] 14.3 Implement secret redaction in logging; verify no key, cookie, or token appears in emitted logs
- [x] 14.4 Verify no provider credential is present in the delivered frontend bundle
- [ ] 14.5 Attach correlation identifiers across API and worker logs; verify a single request is reconstructable from its logs
- [ ] 14.6 Wire Opik tracing for retrieval and generation spans; verify making the telemetry backend unreachable does not fail a user request
- [ ] 14.7 Record operational metrics including token usage and cost per request; verify cost is attributable to a single request
- [ ] 14.8 Verify retry classification: timeouts and 5xx retry, validation and auth failures do not
- [ ] 14.9 Verify all-providers-unavailable preserves the question and job and returns its distinct code

## 15. MCP server

- [x] 15.1 Implement the MCP server in the API process exposing search, get-document, and diagnose tools with strict schemas; verify tool discovery lists complete schemas
- [x] 15.2 Return citations and image metadata from tool results drawn from the shared retrieval core; verify sources match those the web chat returns for the same question
- [x] 15.3 Implement timeouts, rate limiting, and comprehensible errors; verify schema-invalid input names the offending field
- [x] 15.4 Provide host configuration examples; verify against a real host or MCP inspector

## 16. Evaluation

- [ ] 16.1 Implement the harness parsing `docs/eval/golden-set.md`; verify all 10 questions load with their expected sources
- [ ] 16.2 Implement deterministic Recall@k and citation-correctness scoring; verify computed without any model call
- [ ] 16.3 Implement LLM-as-judge scoring with a judge model different from the model under test; verify configuration rejects them being equal
- [ ] 16.4 **Run the golden set, record the baseline, and manually spot-check 10 judge verdicts against human judgement**
- [ ] 16.5 Verify the abstention question abstains and the two clarification questions ask before answering

## 17. CI/CD and delivery

- [ ] 17.1 Add `ci.yml` running backend lint, format check, and pytest, plus frontend lint, typecheck, test, and build; verify it passes on a clean branch
- [ ] 17.2 Add a Playwright happy-path test covering landing → related questions → unresolved → rescue tools → chat → answer with citation → reload → history restored; verify it passes against a deployed instance
- [ ] 17.3 Add `deploy.yml` gated on CI, building versioned images, applying migrations, verifying readiness, and rolling back on failure; verify a forced readiness failure triggers rollback
- [ ] 17.4 Add the reindex workflow on schedule and manual dispatch that exits cheaply when the upstream SHA is unchanged; verify a no-change run performs no embedding
- [ ] 17.5 Complete the security checklist in docs/deployment.md §11 and verify each item

## 18. Demo readiness

- [ ] 18.1 Choose and verify the demo question has strong retrieval results, noting that the corpus has no dedicated FastAPI section; verify the chosen question returns good related questions and citations
- [ ] 18.2 Rehearse the provider-fallback moment and verify it triggers on cue
- [ ] 18.3 Write the README covering setup, architecture, environment variables, deployment, and demo; verify a clean checkout can be run from it alone
- [ ] 18.4 **Verify the full Definition of Done in plan §31 item by item**

## 19. Retrieval quality issues found by agent verification

Raised 2026-08-21 by driving the Skill through a real coding agent against the deployed
index. None blocks the demo; each degrades answer quality in a way that is invisible from
inside the system, because every one of them still produces a confident, well-formed,
correctly-cited answer.

- [ ] 19.1 Deduplicate near-identical chunks in retrieval results; verify a query that
      currently returns the same passage three times returns it once and fills the freed
      budget with distinct evidence. Observed: `deploy-app` returned 3× at 0.6165, and
      `add-domain` 4× — up to half of `top_k` spent on one passage.
- [ ] 19.2 Reconcile `page_title` and `section_title` between `search` and `get_document`;
      verify the same chunk reports identical citation fields through both tools. Observed:
      the two strings swap roles between the tools, so the Skill's "preserve the exact
      retrieved page title" has no single exact value to preserve.
- [ ] 19.3 Fix the MDX title extraction that yields `page_title: "mirror لیارا"` for
      `/paas/nextjs/how-tos/deploy-app`; verify no active chunk carries a title absent from
      its source document. A corrupted title is reproduced verbatim in a user-facing citation.
- [ ] 19.4 Surface truncation explicitly on retrieval results; verify a chunk cut mid-sentence
      is flagged so a caller knows to fetch the full section. Observed: the highest-scoring
      passage for the SSL question was severed exactly before its most actionable clause.
- [ ] 19.5 Evaluate whether `diagnose` should retrieve differently from `search` rather than
      wrapping it; verify a troubleshooting question returns prerequisite and fix content
      ahead of definitional content. Observed: `diagnose` on the SSL failure returned mostly
      "what SSL is" and none of the three passages that actually resolved it.
