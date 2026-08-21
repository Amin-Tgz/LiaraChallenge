## Purpose

Finds the documentation evidence that actually answers a Persian question, combining meaning-based and exact-term search over normalized text, and returning scored, citable evidence that downstream answering can be held accountable to.

## ADDED Requirements

### Requirement: Persian text normalization

The system SHALL apply an identical normalization to indexed text and to incoming queries, covering Arabic/Persian character variants, zero-width non-joiner handling, digit forms, and spacing.

#### Scenario: Character variant equivalence

- **WHEN** a query uses a character variant that differs from the form stored in the documentation
- **THEN** the query still matches the corresponding content

#### Scenario: Symmetry guaranteed

- **WHEN** normalization rules change
- **THEN** indexed content and queries are normalized by the same rules, and content indexed under prior rules is reindexed before the change takes effect

### Requirement: Hybrid retrieval

The system SHALL combine dense semantic retrieval with lexical retrieval and fuse the results using a configurable, explainable method. Fusion weights, result counts, and thresholds SHALL be configurable.

#### Scenario: Semantic match without shared vocabulary

- **WHEN** a question describes a problem using words absent from the documentation
- **THEN** semantically related chunks are still returned

#### Scenario: Exact term match

- **WHEN** a question contains an exact error message, command, or service name
- **THEN** chunks containing that literal string are returned even if their overall semantic similarity is modest

#### Scenario: Fused ordering

- **WHEN** results come from both retrieval methods
- **THEN** the final ordering is produced by the configured fusion method and each result's contributing scores are recoverable

### Requirement: Retrieval output contract

Each retrieval result SHALL include its relevance score, chunk text, metadata, associated images, source URL, section anchor, and the source commit of the index that produced it.

#### Scenario: Result completeness

- **WHEN** retrieval returns a result
- **THEN** that result carries a score, its text, its source URL with anchor, and the index's source commit

#### Scenario: Citation identity is stable

- **WHEN** the same chunk is returned by search and then read through the document tool
- **THEN** both surfaces report the same document page title and section title, with neither inferred from breadcrumb position

#### Scenario: Truncation is explicit

- **WHEN** a stored chunk starts or ends inside a larger split unit
- **THEN** the result marks which edge is truncated so a caller knows to read the full section before relying on the missing context

### Requirement: Retrieval evidence is diverse

The system SHALL remove exact and near-duplicate passages from the ranked result set and SHALL use additional ranked candidates to fill the configured result budget with distinct evidence when available. The duplicate threshold and candidate multiplier SHALL be configurable.

#### Scenario: Duplicate passages do not consume the budget

- **WHEN** multiple documents contain the same or near-identical passage
- **THEN** the highest-ranked occurrence is returned once and the freed result slots contain the next distinct passages

### Requirement: Metadata influences ranking without hiding evidence

The system SHALL use chunk metadata for soft boosting by default. Hard filtering SHALL apply only when user intent for that attribute is explicit and reliable.

#### Scenario: Soft boost

- **WHEN** the session indicates a runtime and the question does not explicitly restrict to it
- **THEN** chunks matching that runtime rank higher, and non-matching chunks remain eligible

#### Scenario: Explicit filter

- **WHEN** the user explicitly restricts the question to a named service
- **THEN** results are limited to that service

### Requirement: Similarity is the exposed unit

The system SHALL express relevance as similarity in configuration, API responses, and logs. Distance SHALL NOT be exposed where similarity is expected.

#### Scenario: Consistent units

- **WHEN** a threshold is configured and a result score is reported
- **THEN** both are similarity values on the same scale and are directly comparable

### Requirement: Retrieval failures are distinguishable

The system SHALL distinguish between an unavailable or empty index, a retrieval execution failure, and a successful search that found nothing above threshold. Each SHALL surface a distinct error code and a user-facing message stating its actual cause.

#### Scenario: No index present

- **WHEN** a query is issued and no index version is active
- **THEN** the response carries the no-active-index error code and states that nothing has been indexed yet, identifying it as a system fault

#### Scenario: Index healthy but nothing relevant

- **WHEN** a query is issued against a healthy index and no result exceeds the threshold
- **THEN** the response carries the no-results-above-threshold code, states that the documentation is indexed but no relevant answer was found, and the question is recorded as an unresolved documentation gap

#### Scenario: Retrieval execution failure

- **WHEN** the underlying search fails
- **THEN** the response carries the retrieval-failed code and is distinguishable from both of the above
