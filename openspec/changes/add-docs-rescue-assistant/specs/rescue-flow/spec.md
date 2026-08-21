## Purpose

The user journey from a single typed question through related questions, resolution feedback, and escalation to one of three rescue tools — holding the question and conversation intact across every hop so the user never retypes and never loses their place.

## ADDED Requirements

### Requirement: Question captured once and persisted immediately

The system SHALL accept a multi-line question on the landing view and persist it to durable storage before any processing begins. The question SHALL remain available for the rest of the session without the user retyping it.

#### Scenario: Question survives immediately

- **WHEN** a user submits a question
- **THEN** the question and its conversation are persisted before retrieval begins

#### Scenario: Carried into every path

- **WHEN** the user moves from related questions to any rescue tool
- **THEN** the original question is already present in that tool's context without retyping

### Requirement: Anonymous session identity

The system SHALL issue each anonymous visitor a session identifier stored in a cookie, and SHALL associate conversations with it. No end-user account or login SHALL be required.

#### Scenario: Session established

- **WHEN** a first-time visitor submits a question
- **THEN** a session identifier is issued and the conversation is associated with it

#### Scenario: Session reused

- **WHEN** a returning visitor with a valid session identifier opens the application
- **THEN** their prior conversations are retrievable

### Requirement: State survives reload and tab reopen

Primary state SHALL NOT live only in client memory or client-side storage. Conversation history and in-flight job status SHALL be recoverable from the server.

#### Scenario: Reload during generation

- **WHEN** a user reloads the page while an answer is being generated
- **THEN** the conversation and the job's current status are restored, and generation is not restarted

#### Scenario: Tab reopened

- **WHEN** a user closes the tab and reopens the application within the session
- **THEN** the prior conversation and its messages are shown

### Requirement: Rescue tool selection

After a user reports that their question remains unresolved, the system SHALL present three paths — an installable Skill, an MCP connection, and in-app chat — described in plain language rather than protocol terminology.

#### Scenario: Tools presented on unresolved

- **WHEN** the user reports the question is still unresolved
- **THEN** the three rescue paths are presented with plain-language descriptions of when each applies

#### Scenario: Movement between tools preserves context

- **WHEN** the user selects one rescue path and then returns and selects another
- **THEN** the original question and conversation are preserved and not restarted

#### Scenario: Backward navigation

- **WHEN** the user navigates back from a rescue tool
- **THEN** the previous step is restored with its prior state intact

### Requirement: Bidirectional text rendering

The interface SHALL be right-to-left for Persian content while rendering code blocks, commands, file paths, and identifiers left-to-right. Mixed Persian and Latin text within a single line SHALL render in the correct order.

#### Scenario: Code direction

- **WHEN** an answer contains a code block or terminal command
- **THEN** it renders left-to-right with its original character order preserved

#### Scenario: Mixed inline content

- **WHEN** a line contains Persian prose with embedded Latin identifiers
- **THEN** both render in their correct directions without visual reordering of the identifier

### Requirement: Answer presentation

Answers SHALL render Markdown structure, syntax-highlighted code blocks each offering a copy action, working links, and cited sources showing page title, section, and link. Where retrieved evidence includes a relevant image, that image SHALL be shown alongside the step or citation it belongs to.

#### Scenario: Copyable code

- **WHEN** an answer contains a code block
- **THEN** a copy action is available for that block

#### Scenario: Citation presentation

- **WHEN** an answer cites documentation
- **THEN** each citation shows the page title and section and links to the exact section

#### Scenario: Image unavailable

- **WHEN** a cited image cannot be loaded
- **THEN** its alternative text is shown and the rest of the answer remains intact

### Requirement: Progress states are legible

The interface SHALL communicate the distinct states of a request — queued, retrieving, generating, retrying, completed, and failed — in terms a non-expert user understands.

#### Scenario: State visibility

- **WHEN** a request moves between states
- **THEN** the interface reflects the current state in plain language

#### Scenario: Failure is explained

- **WHEN** a request fails
- **THEN** the interface states what failed and what the user can do next, rather than a generic failure message

### Requirement: Accessibility

The interface SHALL support keyboard navigation with visible focus states, provide semantic labels, meet contrast requirements, and function on both mobile and desktop viewports.

#### Scenario: Keyboard operation

- **WHEN** a user navigates the primary flow using only a keyboard
- **THEN** every interactive element is reachable and its focus state is visible

### Requirement: Keyboard-first question entry

The primary and follow-up question fields SHALL submit with Enter and SHALL insert a newline with Shift+Enter, without submitting while an input-method composition is active.

#### Scenario: Enter submits

- **WHEN** a user presses Enter in a question field without Shift
- **THEN** the containing form submits exactly once

#### Scenario: Shift Enter keeps multiline input

- **WHEN** a user presses Shift+Enter
- **THEN** a newline is inserted and no request is submitted

### Requirement: User-controlled color theme and navigation

The interface SHALL offer accessible light and dark themes, initialize from the system preference on first visit, remember an explicit choice, and provide a persistent route back to the home question view from every non-home screen.

#### Scenario: Theme preference survives reload

- **WHEN** a user selects the other color theme and reloads the application
- **THEN** the selected theme is restored without relying on the operating-system theme changing

#### Scenario: Home control is available

- **WHEN** a user is on any step after the landing view
- **THEN** a keyboard-accessible control in the top-left header returns to the home question view

### Requirement: Conversation handoff after three turns

The maximum user turns in one chat SHALL be configurable and SHALL default to three. Once reached, the next typed question SHALL be transferred into the landing view's «سؤال شما» field for confirmation as a fresh rescue flow rather than extending the old model context.

#### Scenario: Fourth question becomes a fresh draft

- **WHEN** three user turns already exist and the user enters another question
- **THEN** no fourth chat job is created and the text appears in the landing question field ready for submission
