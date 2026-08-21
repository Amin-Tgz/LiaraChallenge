## Purpose

Answers common questions before any generation happens, by matching the user's question against a curated set of documentation-derived question/answer pairs — the cheapest reliable path, and the source of the feedback signal that reveals documentation gaps.

## ADDED Requirements

### Requirement: FAQ generation from indexed documentation

The system SHALL generate candidate question/answer pairs from indexed documents, each carrying the source document and section it was derived from. Generation SHALL be repeatable and SHALL support processing only documents added or modified since the last generation run.

#### Scenario: Initial generation

- **WHEN** generation runs against a freshly built index
- **THEN** candidate pairs are produced for in-scope documents and each pair records its originating document and source URL

#### Scenario: Incremental generation

- **WHEN** generation runs again after some documents changed
- **THEN** pairs are generated only for added or modified documents, and existing pairs for unchanged documents are left intact

#### Scenario: Malformed generation output rejected

- **WHEN** a generated pair does not conform to the required structure
- **THEN** it is rejected and recorded rather than stored, and the run continues

#### Scenario: Generation capacity is configurable

- **WHEN** the configured FAQ count and output-token budget are changed
- **THEN** both values are sent to the generator, while answer depth is determined by the available evidence rather than a fixed brevity target

#### Scenario: Generated answers are complete and precise

- **WHEN** a document supports prerequisites, ordered steps, variants, limitations, warnings, or a verification method relevant to a generated question
- **THEN** the answer includes those supported details completely and precisely without inventing facts, padding the answer, or prioritizing candidate count over quality

#### Scenario: Forced full regeneration is atomic per document

- **WHEN** an operator requests regeneration for unchanged documents
- **THEN** each document's prior active FAQ entries remain available until its replacement output validates and commits, after which only the replacement set stays active

### Requirement: Semantic matching against a threshold

The system SHALL match an incoming question against stored FAQ questions by embedding similarity, returning at most the configured number of results, and SHALL NOT return results scoring below the configured similarity threshold.

#### Scenario: Confident match

- **WHEN** a question's similarity to stored FAQ questions exceeds the threshold
- **THEN** matching entries are returned ordered by combined semantic similarity and curated priority, each with a short answer and a source link

#### Scenario: Weak match suppressed

- **WHEN** no stored question exceeds the threshold
- **THEN** no FAQ results are shown, and the user is told nothing relevant was found and offered the rescue tools

#### Scenario: Threshold is configurable at runtime

- **WHEN** an administrator changes the similarity threshold
- **THEN** subsequent matching uses the new value without redeployment

#### Scenario: Short ambiguous input requires stronger evidence

- **WHEN** a very short question such as a greeting has only weak semantic matches
- **THEN** the configured short-query threshold suppresses those unrelated results

#### Scenario: Duplicate questions are returned once

- **WHEN** equivalent active FAQ questions originate from multiple documentation pages
- **THEN** the response keeps the highest-ranked occurrence once and fills remaining slots with distinct questions when available

### Requirement: FAQ path is synchronous and does not generate

The FAQ path SHALL resolve within the request, without enqueuing a job and without invoking a language model for answering.

#### Scenario: No generation cost

- **WHEN** a question is answered from the FAQ path
- **THEN** no answer-generation model call is made and the only model usage is the query embedding

### Requirement: Resolution feedback captured

Every presented FAQ result SHALL offer the user a way to report that it resolved their question or that it did not. Feedback SHALL be persisted and associated with the question, the presented entries, and the session.

#### Scenario: Resolved

- **WHEN** a user marks that they got their answer
- **THEN** the outcome is stored against that question and the entries shown

#### Scenario: Unresolved

- **WHEN** a user marks that they still have not found their answer
- **THEN** the outcome is stored, the question is recorded as an unresolved documentation gap, and the rescue tools are presented

### Requirement: Interaction signals recorded for ranking

The system SHALL record impressions, selections, resolution outcomes, and transitions from FAQ to each rescue tool, so ordering can later incorporate observed behavior.

#### Scenario: Transition recorded

- **WHEN** a user moves from FAQ results to a rescue tool
- **THEN** which tool was chosen is recorded against that question

### Requirement: Presentation reflects data provenance

Until behavioral popularity data exists, the interface SHALL present these entries as related questions rather than as frequently asked questions.

#### Scenario: Labeling

- **WHEN** FAQ results are displayed
- **THEN** they are labeled as related questions
