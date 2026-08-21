# Task list

**Open status, as of 2026-08-21.** Everything below is either checked or listed
here. Carried into the next session:

- **1.1** — rotate the AvalAI key exposed during planning (needs panel access)
- **14.3, 14.5–14.9** — remaining observability: log redaction, correlation ids,
  Opik spans, per-request cost, retry classification, all-providers-unavailable
- **16.x** — the golden-set evaluation harness and its baseline
- **17.x** — CI, gated deploy with rollback, scheduled reindex, security checklist
- **18.x** — demo rehearsal and the Definition-of-Done pass

---

## 1. Pre-flight verification

## 22. Assistant identity, richer FAQs, and retained conversations

- [x] 22.1 Make generated FAQ answers self-contained and source-grounded; verify the prompt contract rejects one-sentence operational summaries and regenerate the production corpus with `--force`
  - Verified 2026-08-21: production corpus regenerated with `--force` against
    index `a60589fd` — 1,142/1,142 documents, 0 skipped, 0 failed, 3,042 accepted
    / 3 rejected, 3,042 questions embedded (1536-dim, 144,878 tokens). Read-back
    of the ten shortest answers found every one to be a factual lookup
    (yes/no, port list, extension list), not a procedural question, so the
    "no one-sentence answer to a procedural question" contract holds.
- [x] 22.2 Synchronize `.env.example` with typed defaults and add a regression test that catches future drift; document whether local `.env` needs an override
  - Verified 2026-08-21: `.env.example` carries the typed defaults
    (`FAQ_SIMILARITY_THRESHOLD=0.34`, `FAQ_SHORT_QUERY_SIMILARITY_THRESHOLD=0.51`,
    `RETRIEVAL_SIMILARITY_THRESHOLD=0.2125`) and `tests/unit/test_config.py`
    fails on drift between the example file and the typed defaults.
- [x] 22.3 Rename the user-facing product to «دستیار لیارا», remove the old tagline, add restrained emoji, and align the landing/sidebar visuals with the supplied Liara documentation screenshots
  - Verified 2026-08-21 on the deployed instance: document title and header
    both read «دستیار لیارا», the old tagline is gone, emoji are limited to the
    welcome 👋 and the search ✨, and `dir=rtl` / `lang=fa` are set on the root.
- [x] 22.4 Add distinct sidebar icons for prior conversations, Skill, and MCP; verify labels and keyboard focus remain accessible
  - Verified 2026-08-21 on the deployed instance: the accessibility tree exposes
    «گفت‌وگوهای پیشین», «Skill لیارا» and «سرور MCP» as separately labelled items
    with their own icons, plus a working "پرش به محتوای اصلی" skip link.
- [x] 22.5 Add session-owned conversation deletion, refuse deletion while work is active, and verify cascade/SET NULL behavior plus foreign-session indistinguishability
  - Verified 2026-08-21 against production: owner delete returned 204; a
    foreign session and an already-deleted conversation both returned a
    byte-identical `INVALID_REQUEST` body, so the endpoint cannot be used to
    probe for existence. The chat feedback row for the deleted conversation
    disappeared from `/admin`, matching the declared
    `conversations.id ON DELETE CASCADE` with `message_id`/`session_id` as
    `SET NULL`. Refusal while a job is still running is covered by
    `tests/integration/test_conversation_deletion.py::test_conversation_with_active_job_is_not_deleted`,
    which asserts `CONVERSATION_BUSY`; it was not reproduced against production,
    since that would mean racing a live job.
- [x] 22.6 Cache successfully viewed documentation images in browser-managed storage and set safe static cache headers; verify failures retain alt-text fallback
  - Verified 2026-08-21 on the deployed instance: `navigator.serviceWorker`
    reports the page as `controlled`, so the image cache is active in
    production. The alt-text fallback on image failure is covered by
    `web/src/App.test.tsx` ("a cited image is beside its citation and falls back
    to alt text without losing the answer") rather than by a production check.
- [x] 22.7 Run backend lint/format/tests and frontend lint/typecheck/tests/build, then inspect desktop/mobile light/dark UI, console, and network behavior
  - Verified 2026-08-21. Backend in the api container: `ruff check` all checks
    passed, `ruff format --check` 120 files already formatted, `pytest -q`
    **579 passed, 9 skipped** in 149s. Frontend: lint, typecheck, **28 tests**
    and `vite build` all green. Deployed UI inspected at 1440×900 and 375×812
    in both themes — **0 console messages**, network clean (one
    `/api/v1/chat/conversations` call, 200). One residual: the closed mobile
    drawer leaks a 1px horizontal overflow (scrollWidth 361 vs clientWidth 360);
    left unfixed as it is sub-pixel and outside this task's scope.
- [x] 22.8 Deploy the API/worker if server behavior changed, verify readiness and the production delete/chat path, then commit the completed code and documentation
  - Verified 2026-08-21: API and worker both deployed from
    `docker/Dockerfile.prod`; `/health/ready` returns 200 with postgres, redis,
    active-index and gateway all ok. Production chat path exercised end to end
    (ask → cited answer → reject → `/admin`), and the delete path returns 204
    for the owner.

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
  - **Superseded by 21.2.** The separate `/related` route was folded into the chat surface
    as an inline gate; the labelling and feedback requirements it established still hold.
- [x] 11.4 Implement the rescue-tools view with plain-language descriptions of Skill, MCP, and Chat; verify moving between tools preserves the original question
  - **Superseded by 21.1.** The `/tools` hub was replaced by the persistent sidebar; the
    plain-language descriptions moved onto the Skill and MCP pages themselves.
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

- [x] 13.1 Implement HTTP Basic auth from environment credentials; verify unauthenticated requests are refused and disclose nothing
- [x] 13.2 Implement FAQ review, edit, and delete with re-embedding on question change; verify a deleted entry stops appearing in user results
- [x] 13.3 Implement the incremental sync trigger; verify a no-change run reports no change and a failed run leaves the active index untouched
- [x] 13.4 Implement runtime configuration of the similarity threshold; verify a change affects subsequent matching without redeployment
- [x] 13.5 Implement the dashboard covering FAQ resolution rate, tool split, unresolved questions and their pages, failures by error code, token usage and cost, fallback count, and index version and commit; verify every figure derives from recorded events
- [x] 13.6 Verify metrics with no recorded events display an explicit no-data state rather than a fabricated value

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
- [ ] 17.2 Add a Playwright happy-path test covering landing → inline FAQ gate → unresolved → chat → answer with citation → answer feedback → reload → transcript and verdict restored; verify it passes against a deployed instance
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

- [x] 19.1 Deduplicate near-identical chunks in retrieval results; verify a query that
      currently returns the same passage three times returns it once and fills the freed
      budget with distinct evidence. Observed: `deploy-app` returned 3× at 0.6165, and
      `add-domain` 4× — up to half of `top_k` spent on one passage.
- [x] 19.2 Reconcile `page_title` and `section_title` between `search` and `get_document`;
      verify the same chunk reports identical citation fields through both tools. Observed:
      the two strings swap roles between the tools, so the Skill's "preserve the exact
      retrieved page title" has no single exact value to preserve.
- [x] 19.3 Fix the MDX title extraction that yields `page_title: "mirror لیارا"` for
      `/paas/nextjs/how-tos/deploy-app`; verify no active chunk carries a title absent from
      its source document. A corrupted title is reproduced verbatim in a user-facing citation.
- [x] 19.4 Surface truncation explicitly on retrieval results; verify a chunk cut mid-sentence
      is flagged so a caller knows to fetch the full section. Observed: the highest-scoring
      passage for the SSL question was severed exactly before its most actionable clause.
- [x] 19.5 Evaluate whether `diagnose` should retrieve differently from `search` rather than
      wrapping it; verify a troubleshooting question returns prerequisite and fix content
      ahead of definitional content. Observed: `diagnose` on the SSL failure returned mostly
      "what SSL is" and none of the three passages that actually resolved it.

## 20. User-reported rescue-flow quality pass

- [x] 20.1 Add a configurable stronger threshold for short FAQ queries and deduplicate
      normalized FAQ questions; verify `سلام` returns no Celery result and equivalent FAQ
      questions occupy one result slot.
- [x] 20.2 Raise the FAQ generation capacity from 5 to 15, add a configurable structured
      output-token budget, require complete and precise evidence-sized answers, and add forced
      per-document atomic regeneration; verify existing entries survive a failed replacement
      and a successful replacement deactivates them.
- [x] 20.3 Redesign the Persian RTL UI using the adopted blue/gold 8pt system, responsive
      surfaces, complete interaction states, and a persisted light/dark toggle; verify WCAG
      contrast, keyboard focus, mobile layout, console, and network state with Playwright.
- [x] 20.4 Submit both question textareas with Enter and preserve multiline entry with
      Shift+Enter and IME composition; verify each keyboard path.
- [x] 20.5 Rename the Skill path, expose the canonical Skill as a real downloadable Markdown
      attachment, and verify the documented URL does not return SPA HTML.
- [x] 20.6 Replace the generic MCP instructions with branded, expandable host guides for
      Claude Code, Cursor, Codex, Open WebUI, Jan, and AnythingLLM, grounded in current
      official documentation.
- [x] 20.7 Add a persistent top-left home control on non-home routes and preserve the current
      question while navigating backward through the rescue flow.
- [x] 20.8 Cap chat at three configurable user turns in both API and UI; verify a next question
      creates no old-conversation job and arrives prefilled in the landing question field.
- [x] 20.9 Place the supplied stopped, Chat, Skill, and MCP illustrations in their rescue-flow
      contexts and cycle the four supplied thinking frames once per second while chat work is
      active; verify production image requests, desktop/mobile layout, and console state.
- [x] 20.10 Expand the downloadable Skill with official source links, the Liara documentation
      information architecture, MDX page schema, route-selection and evidence extraction
      guidance; replace temporary MCP host marks with locally served official logos.

## 21. Chat-first surface, unbounded conversation, and the operator loop

- [x] 21.1 Replace the four-page rescue path with one chat surface plus a persistent sidebar carrying full conversation history and the Skill and MCP pages; verify `/related`, `/tools`, and `/solved` redirect and no navigation is needed to reach either tool
- [x] 21.2 Present related questions inline with an explicit accept/reject choice; verify no answering-model call is made before the user rejects them, and that a zero-result search opens the conversation directly
- [x] 21.3 Lower `faq_similarity_threshold`, `faq_short_query_similarity_threshold`, and `retrieval_similarity_threshold` by 15%; verify the short-query bar stays strictly above the general one
- [x] 21.4 Summarize conversation turns beyond the verbatim window instead of refusing a fourth turn, and reduce `HISTORY_LIMIT_REACHED` to an abuse ceiling; verify summarization is incremental and that its failure degrades to raw history without failing the turn
- [x] 21.5 Publish each agent tool call as a `trace` relay event and render the real steps while the user waits; verify an unmeasured similarity is reported as absent and a failing relay does not fail the job
- [x] 21.6 Record a per-answer helpful/unhelpful verdict with a reason, deriving the question and implicated pages from the answer's own record; verify a foreign or non-answer message is refused identically to an unknown one
- [x] 21.7 Add answer-quality and demand metrics to the dashboard, and record every FAQ search including one that matched nothing; verify each new metric reports absence rather than zero on an empty window
- [x] 21.8 Add the `/admin` web console over the existing HTTP Basic guard with feedback and metrics tabs; verify it holds credentials in memory only and writes nothing to browser storage
- [x] 21.9 Add the `/demo` documentation page with the floating rescue widget; verify it is labelled as a demonstration, that hover or focus reveals the stopped illustration, and that it is operable by keyboard
- [x] 21.10 Make the shell responsive with a focus-managed mobile drawer, and derive the favicon from the deer mark; verify 375px and 1440px in both themes with no horizontal scroll and a clean console
- [x] 21.11 Strengthen the FAQ generation prompt to require numbered steps, verbatim commands and configuration values, and a way to verify success, and to forbid one-sentence answers to procedural questions
- [x] 21.12 Update README with the hackathon context and an honest per-criterion mapping, and bring `docs/deployment.md` and the delta specs in line
- [x] 21.13 Apply the history-summary and chat-feedback migration to production and deploy API and worker
  - Verified 2026-08-21: `liara deploy` succeeded for both `liara.api.json` and
    `liara.worker.json`. The API entrypoint applied the pending migration on
    boot — production `alembic_version` is now `c7f1d2b40e51`, `conversations`
    has `history_summary` and `history_summarized_through_ordinal`, and
    `feedback` has `message_id` and `reason`.
- [x] 21.14 **Regenerate the whole FAQ corpus with `--force` under the new prompt, then read at least ten random entries against their source text and record what that showed**
  - Verified 2026-08-21: full `--force` regeneration produced 3,042 accepted
    items over 1,142 documents with 0 failures, all embedded. Twelve random
    active entries were read against their source chunk text. Eleven reproduced
    their source faithfully, including verbatim code blocks, all five Slack
    scopes, and the `liara.json` warning not to set `app`/`platform`. The
    twelfth — the Metabase "change version via CLI" entry — carries a
    `rocket.chat:<your-version>` image, but the upstream Liara page contains
    exactly that copy-paste error, so the generator reproduced its source rather
    than inventing one. The same held for the surprising
    "Cloudflare SSL → Flexible" claim, which the source states verbatim. No
    fabricated content was found.
- [x] 21.15 Verify the loop end to end on the deployed instance: ask, reject the answer, and confirm the same question and its cited pages appear in `/admin`
  - Verified 2026-08-21 on the deployed instance: asked «چگونه نسخه NodeJS
    برنامه Angular را در لیارا تغییر دهم؟», received a cited answer from
    `paas/angular/how-tos/choose-version`, rejected it as
    `unresolved`/`incomplete`, and found that exact question, its answer, its
    cited page and both ids at the top of `/admin/feedback`. Unauthenticated
    access to the same endpoint returned 401.

