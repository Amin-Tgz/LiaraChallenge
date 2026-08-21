## Purpose

Answers questions that the FAQ path could not, using a deliberately constrained agent that may only search and read Liara's documentation, must cite what it claims, must ask before guessing when a missing detail changes the answer, and must say so plainly when the documentation does not contain an answer.

## ADDED Requirements

### Requirement: Bounded tool access

The agent SHALL have access only to an allowlisted set of documentation tools — searching documents, reading a specific document or section, and searching related questions. It SHALL NOT have access to general-purpose capabilities such as arbitrary network access, code execution, or filesystem access.

#### Scenario: Only allowlisted tools available

- **WHEN** the agent processes any question
- **THEN** the only tools it can invoke are the documentation tools, and any other capability is unavailable

#### Scenario: Retrieval confined to Liara documentation

- **WHEN** the agent retrieves evidence
- **THEN** all evidence originates from the indexed Liara documentation and no other source

### Requirement: Enforced execution limits

Each conversational turn SHALL enforce a maximum number of tool calls, a maximum number of query rewrites, a token budget, and a timeout. All limits SHALL be configurable.

#### Scenario: Tool call ceiling

- **WHEN** the agent reaches the configured maximum tool calls within a turn
- **THEN** it stops retrieving and answers from the evidence gathered so far, or abstains if that evidence is insufficient

#### Scenario: Timeout

- **WHEN** a turn exceeds its configured timeout
- **THEN** the turn terminates, the failure is recorded with a distinct error code, and the user's question and conversation are preserved

### Requirement: Mandatory citation of technical claims

Every technical claim in an answer SHALL be traceable to retrieved evidence, and the answer SHALL present the corresponding sources with links to the exact section.

#### Scenario: Claims are cited

- **WHEN** an answer states a technical fact, command, or configuration value
- **THEN** a citation to the retrieved documentation supporting it is included

#### Scenario: Citations resolve to real evidence

- **WHEN** an answer presents a citation
- **THEN** that citation corresponds to a chunk actually returned by retrieval for this turn

### Requirement: Abstention when evidence is insufficient

The agent SHALL NOT produce an answer unsupported by retrieved evidence. When evidence is insufficient, it SHALL state this explicitly and suggest what the user can do next.

#### Scenario: No supporting evidence

- **WHEN** retrieval succeeds but the returned evidence does not support an answer
- **THEN** the agent states that the documentation does not appear to cover the question, carries the no-evidence error code, and suggests a next step rather than producing a plausible answer

#### Scenario: Recorded as a documentation gap

- **WHEN** the agent abstains for lack of evidence
- **THEN** the question is recorded for documentation-gap analytics

### Requirement: Clarification only when it changes the answer

The agent SHALL ask a clarifying question only when the missing detail would materially change the answer. It SHALL NOT ask when the answer would be the same regardless.

#### Scenario: Load-bearing ambiguity

- **WHEN** a question's answer depends on which service, runtime, framework, or deployment mode the user is using, and that is not determinable from the conversation
- **THEN** the agent asks for that specific detail before answering

#### Scenario: Ambiguity that does not matter

- **WHEN** a question is under-specified but the answer would be identical across the plausible interpretations
- **THEN** the agent answers without asking

### Requirement: Session technical profile

The system SHALL maintain a per-session technical profile — service, runtime, framework, experience level, current goal, deployment mode, and known error — updated from the conversation and used to boost retrieval, inform clarification, and calibrate explanation depth. It SHALL NOT constitute a durable personal profile.

#### Scenario: Profile informs later turns

- **WHEN** a user states their runtime in one turn and asks a related question in a later turn
- **THEN** the later turn uses that runtime without asking again

#### Scenario: Scoped to the session

- **WHEN** a session ends
- **THEN** the profile does not persist as a personal profile across unrelated sessions

### Requirement: Durable, resumable job execution

Chat requests SHALL be persisted before execution and processed as queued jobs that survive client disconnection and worker restart. Each request SHALL carry an idempotency key so that resubmission does not create duplicate work.

#### Scenario: Client disconnects

- **WHEN** the client disconnects while an answer is being generated
- **THEN** generation continues and the completed answer is available when the client returns

#### Scenario: Duplicate submission

- **WHEN** the same request is submitted twice with the same idempotency key
- **THEN** only one job is created and both submissions observe the same result

#### Scenario: Worker restart

- **WHEN** the worker restarts while a job is in progress
- **THEN** the job resumes from persisted state or is safely retried, and the user's question is not lost

#### Scenario: Repeated failure terminates

- **WHEN** a job exhausts its permitted retries
- **THEN** it enters a terminal failed state with a distinct error code rather than retrying indefinitely

### Requirement: Streamed delivery with reconnection

Answers SHALL be streamed to the client as they are produced, and the stream SHALL support reconnection without losing content already generated.

#### Scenario: Progressive rendering

- **WHEN** an answer is being generated
- **THEN** partial content is delivered to the client before the answer is complete

#### Scenario: Reconnect mid-stream

- **WHEN** a client reconnects after an interrupted stream
- **THEN** it receives the content it missed and continues from the current position

### Requirement: Retrieved content is data, not instruction

The system SHALL treat retrieved documentation as untrusted data. Instructions embedded within documentation content SHALL NOT alter the agent's behavior.

#### Scenario: Injection attempt in content

- **WHEN** retrieved content contains text resembling instructions to the model
- **THEN** the agent does not follow them and answers the user's original question

### Requirement: History summarized rather than truncated

Conversation turns beyond the configured verbatim window SHALL be condensed into a running summary supplied to the agent as context. Each turn SHALL be summarized at most once. A summarization failure SHALL degrade to the raw recent history and SHALL NOT fail the turn. The summary SHALL be supplied with an explicit boundary marking it as data rather than instruction.

#### Scenario: Older turns become a summary

- **WHEN** a conversation exceeds the configured trigger and turns fall outside the verbatim window
- **THEN** those turns are represented to the agent by a summary and the recent turns are still supplied verbatim

#### Scenario: Summarization is incremental

- **WHEN** a further turn falls outside the window on a later request
- **THEN** only the newly excluded turns are summarized, on top of the existing summary

#### Scenario: Failure costs context, not the answer

- **WHEN** the summarization call fails or times out
- **THEN** the turn proceeds using the raw recent history and the failure is recorded

### Requirement: Observable search steps

While a job runs, the system SHALL publish each documentation search the agent performs — the tool, the query as written, the number of results, and the highest similarity when the tool measured one — on the same relay the answer streams over. Publishing SHALL NOT be able to fail the job, and a step that did not happen SHALL NOT be reported.

#### Scenario: A search step is published as it happens

- **WHEN** the agent completes a tool call
- **THEN** an event naming the tool, the query, and what came back is published to the job's stream

#### Scenario: Unmeasured similarity is reported as absent

- **WHEN** a tool returns results without a similarity score
- **THEN** the step reports no similarity rather than a zero

#### Scenario: A broken relay does not break the answer

- **WHEN** publishing a step fails
- **THEN** the failure is recorded and the turn completes normally

### Requirement: Answer feedback joined to its evidence

The system SHALL accept a verdict on a specific assistant answer and SHALL derive the question and the documentation pages implicated from that answer's own record rather than from the submitting client. A verdict on a message that is not an assistant answer belonging to the requesting session SHALL be refused identically to one naming a message that does not exist.

#### Scenario: Cited pages come from the answer

- **WHEN** a verdict is recorded on an answer
- **THEN** the stored record carries the answer's citations as the implicated pages and the question it replied to, neither of them supplied by the client

#### Scenario: A foreign or non-answer message is refused

- **WHEN** a verdict names a message belonging to another session, or a message that is not an assistant answer
- **THEN** it is refused with the same response as one naming an unknown message

