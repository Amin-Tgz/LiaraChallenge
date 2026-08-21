## Purpose

Exposes the same documentation retrieval to users working inside their own coding agents — an installable Skill that teaches the agent the rescue workflow, and an MCP server that connects the agent directly to live Liara documentation — so users who prefer their own tooling never have to visit the web application.

## ADDED Requirements

### Requirement: MCP server exposes documentation tools

The system SHALL expose an MCP server providing tools to search Liara documentation, retrieve a specific document, and diagnose a described Liara issue. Each tool SHALL declare a precise input and output schema.

#### Scenario: Tool discovery

- **WHEN** an MCP host connects to the server
- **THEN** the three tools are listed with complete input and output schemas

#### Scenario: Search returns citable evidence

- **WHEN** the search tool is invoked with a query
- **THEN** results include chunk text, source URL with section anchor, relevance score, and image metadata where present

#### Scenario: Invalid input rejected clearly

- **WHEN** a tool is invoked with input violating its schema
- **THEN** a comprehensible error is returned identifying the offending field, and no partial work is performed

### Requirement: MCP operational constraints

The MCP server SHALL enforce request timeouts and rate limiting, and SHALL return comprehensible errors on failure. Access to public documentation SHALL NOT require a Liara account credential; any credential requirement SHALL exist solely to protect this project's own service.

#### Scenario: No Liara credential needed

- **WHEN** a user configures the MCP server to read public documentation
- **THEN** no Liara account credential is required

#### Scenario: Rate limit exceeded

- **WHEN** a client exceeds the configured request rate
- **THEN** requests are rejected with the rate-limited error code and a comprehensible message

#### Scenario: Upstream failure surfaced

- **WHEN** retrieval fails while serving a tool call
- **THEN** the tool returns an error identifying the cause rather than an empty successful result

### Requirement: MCP installation is documented and verified

The system SHALL provide working configuration examples for common MCP hosts and SHALL be verified against at least one real host or inspector.

#### Scenario: Configuration provided

- **WHEN** a user consults the installation documentation
- **THEN** copy-ready configuration is available for common coding agent hosts

#### Scenario: Verified against a host

- **WHEN** the MCP server is released
- **THEN** its tools have been exercised successfully from a real host or inspector

#### Scenario: Host-specific setup is discoverable

- **WHEN** a user chooses a supported coding agent or chat host
- **THEN** a branded card reveals copy-ready steps naming the current settings screen or configuration-file location for that host and links to its official documentation

### Requirement: Diagnose prioritizes actionable evidence

The diagnose tool SHALL retain the verbatim symptom and error text while performing an additional troubleshooting-oriented retrieval pass, then deduplicate and bound the combined evidence so prerequisite and remediation passages are not displaced by repeated definitional content.

#### Scenario: Troubleshooting evidence is promoted

- **WHEN** a failure query has both definitional and fix-oriented documentation
- **THEN** diagnose includes distinct prerequisite or remediation evidence within its configured result budget

### Requirement: Skill encodes a problem-solving workflow

The system SHALL provide an installable Skill that instructs a coding agent to identify the relevant service and intent, ask for missing information that changes the answer, retrieve documentation evidence before answering, answer only from that evidence, present runnable commands, preserve sources and relevant images, avoid guessing when evidence is absent, and propose a verification step.

#### Scenario: Retrieval precedes answering

- **WHEN** an agent following the Skill receives a Liara question
- **THEN** it retrieves documentation evidence before composing an answer

#### Scenario: Evidence-bound answering

- **WHEN** an agent following the Skill finds no supporting evidence
- **THEN** it reports that rather than producing an unsupported answer

#### Scenario: Sources and images preserved

- **WHEN** an agent following the Skill answers from retrieved evidence containing a relevant image
- **THEN** the answer retains the source citations and the relevant image reference

### Requirement: Skill is installable and versioned

The Skill SHALL ship with installation instructions, a version identifier, and at least one worked example demonstrating correct behavior.

#### Scenario: Installation documented

- **WHEN** a user consults the Skill's documentation
- **THEN** installation steps, a version, and a worked example are present

#### Scenario: Skill artifact downloads from the product

- **WHEN** a user follows the web installation guide or activates its download action
- **THEN** the server returns the canonical versioned `SKILL.md` as a Markdown attachment rather than the SPA HTML shell

### Requirement: Consistent evidence contract across surfaces

The web chat, the MCP tools, and the Skill workflow SHALL draw on the same retrieval behavior and the same citation contract, so equivalent questions yield consistent evidence and sources.

#### Scenario: Consistent sources

- **WHEN** the same question is asked through the web chat and through the MCP tools
- **THEN** the cited documentation sources are drawn from the same index and resolve to the same sections
