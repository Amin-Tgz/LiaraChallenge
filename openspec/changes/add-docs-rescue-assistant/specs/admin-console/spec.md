## Purpose

Gives the operator control over the curated FAQ set and runtime retrieval behavior, a way to bring the index up to date on demand, and a view of whether the system is actually resolving questions — including which documentation gaps it has discovered.

## ADDED Requirements

### Requirement: Administrative access is protected

Administrative functions SHALL require authentication using credentials supplied through environment configuration. Credentials SHALL NOT be stored in the repository. No end-user authentication SHALL be introduced.

#### Scenario: Unauthenticated access refused

- **WHEN** an unauthenticated request reaches any administrative function
- **THEN** it is refused and no administrative data is disclosed

#### Scenario: End users unaffected

- **WHEN** an ordinary user uses the rescue flow
- **THEN** no login is required of them

### Requirement: FAQ management

An administrator SHALL be able to trigger generation of FAQ entries, review them, edit them, and delete them. Curated entries SHALL be distinguishable from ungenerated or unreviewed ones.

#### Scenario: Generation triggered

- **WHEN** an administrator triggers FAQ generation
- **THEN** entries are produced from the active index and presented for review

#### Scenario: Entry deleted

- **WHEN** an administrator deletes an entry
- **THEN** it no longer appears in user-facing related-question results

#### Scenario: Entry edited

- **WHEN** an administrator edits an entry's question or answer
- **THEN** the change is reflected in subsequent matching, including re-embedding of a changed question

### Requirement: Incremental synchronization on demand

An administrator SHALL be able to trigger a synchronization that detects documentation changes since the active index and processes only added or modified documents.

#### Scenario: Sync with changes

- **WHEN** synchronization is triggered and upstream documents have changed
- **THEN** only added and modified documents are reprocessed and the result is reported

#### Scenario: Sync with no changes

- **WHEN** synchronization is triggered and nothing has changed upstream
- **THEN** the run completes without reprocessing and reports that no change was found

#### Scenario: Sync failure preserves service

- **WHEN** synchronization fails partway
- **THEN** the previously active index remains in service and the failure is reported with its cause

### Requirement: Runtime configuration

An administrator SHALL be able to adjust retrieval tuning values — including the FAQ similarity threshold — and have them take effect without redeployment. Values SHALL be expressed as similarity.

#### Scenario: Threshold change takes effect

- **WHEN** an administrator changes the similarity threshold
- **THEN** subsequent user questions are matched using the new value

### Requirement: Operational dashboard

The system SHALL present a dashboard showing the proportion of questions resolved at the FAQ stage, the distribution of rescue tool selections, the most frequent unresolved questions, the documentation pages attracting the most unresolved feedback, failure counts by cause, token usage and cost, provider fallback occurrences, and the active index's status, source commit, and version.

#### Scenario: Resolution and routing visible

- **WHEN** an administrator views the dashboard
- **THEN** the FAQ resolution rate and the distribution across Skill, MCP, and Chat are shown

#### Scenario: Documentation gaps visible

- **WHEN** questions have been recorded as unresolved
- **THEN** the most frequent ones and their associated documentation pages are listed

#### Scenario: Failures attributed by cause

- **WHEN** failures have occurred
- **THEN** they are counted by the same error codes used in the API and logs

#### Scenario: Index state visible

- **WHEN** an administrator views the dashboard
- **THEN** the active index version, its source commit, and its status are shown

### Requirement: Dashboard reflects real recorded data

Displayed figures SHALL derive from recorded events. Placeholder or fabricated values SHALL NOT be presented as measurements.

#### Scenario: No data yet

- **WHEN** a metric has no recorded events
- **THEN** the dashboard indicates the absence of data rather than displaying a fabricated value

### Requirement: Answer-quality and demand metrics

The dashboard SHALL report, from recorded events: the share of generated answers judged helpful, the documentation pages most often backing rejected answers, the distribution of rejection reasons, the most frequently asked questions grouped on their normalized form, the most cited documentation pages, question volume over time, the abstention rate, and the share of FAQ searches returning any result above the threshold. Each SHALL follow the existing no-data contract.

#### Scenario: Poorly rated pages are identifiable

- **WHEN** answers citing a documentation page are repeatedly judged unhelpful
- **THEN** that page appears in the lowest-rated pages metric with its count

#### Scenario: Demand is counted per question, not per result

- **WHEN** one search returns several related questions
- **THEN** the question is counted once in the most-asked metric, not once per result shown

#### Scenario: A metric with no events reports its absence

- **WHEN** no chat feedback has been recorded in the window
- **THEN** the satisfaction rate reports no data rather than a zero

### Requirement: Administrative web console

The system SHALL provide a web interface to the administrative routes presenting recorded feedback and the dashboard metrics. It SHALL introduce no authentication mechanism of its own, SHALL reuse the existing guard, and SHALL NOT persist administrator credentials in browser storage.

#### Scenario: Console is closed before authentication

- **WHEN** the console is opened without credentials
- **THEN** only a credential prompt is shown and no administrative data is requested

#### Scenario: A refusal discloses nothing extra

- **WHEN** the supplied credentials are rejected
- **THEN** the console reports the server's single refusal message and remains closed

#### Scenario: Credentials are not written to disk

- **WHEN** credentials have been entered
- **THEN** no part of them is present in browser storage, and reloading requires entering them again

### Requirement: Individual feedback is readable

The system SHALL expose recorded feedback entries with the question, the answer judged, the reason given, and the documentation pages implicated, filterable by stage, outcome, and time window.

#### Scenario: A complaint can be read in context

- **WHEN** an administrator reads recorded feedback
- **THEN** each entry shows the question, the answer that was judged, and the pages that answer cited

