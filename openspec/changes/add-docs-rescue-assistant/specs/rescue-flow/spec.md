## Purpose

The user journey from a single typed question through related questions, resolution feedback, and escalation to the assistant — holding the question and conversation intact so the user never retypes and never loses their place. The journey happens on one chat surface; the Skill and MCP paths are reachable from a persistent sidebar rather than being a step in it.

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

### Requirement: Single chat surface with an inline related-questions gate

The landing view SHALL be the conversation surface. Submitting a question SHALL NOT change route: related questions SHALL be presented inline for the user to judge, and the answering model SHALL NOT be called until the user reports them insufficient. When no related question clears the threshold, the system SHALL open the conversation directly.

#### Scenario: Related questions offered before any generation

- **WHEN** a submitted question matches related questions above the threshold
- **THEN** they are shown inline with an explicit accept/reject choice, and no answering model call has been made

#### Scenario: Rejection opens the conversation with the same wording

- **WHEN** the user reports the related questions did not help
- **THEN** a conversation is opened with the question exactly as typed, and the rejection is recorded with the entries that were on screen

#### Scenario: No match goes straight to the assistant

- **WHEN** no related question clears the threshold
- **THEN** the conversation opens directly without an intermediate step

### Requirement: Persistent navigation for conversations and rescue tools

The system SHALL present conversation history and the Skill and MCP paths in a persistent sidebar, described in plain language rather than protocol terminology. History SHALL NOT be capped in the interface. On narrow viewports the sidebar SHALL become a dismissible drawer that manages focus.

#### Scenario: Every conversation is reachable

- **WHEN** a session has any number of prior conversations
- **THEN** all of them are listed in the sidebar, and the current one is marked

#### Scenario: Rescue tools always reachable

- **WHEN** the user is anywhere in the application
- **THEN** the Skill and MCP paths are reachable in one action, with plain-language descriptions of when each applies

#### Scenario: Drawer is keyboard-operable

- **WHEN** the sidebar is opened as a drawer and the user presses Escape
- **THEN** it closes and focus returns to the control that opened it

### Requirement: Documentation embed demonstration

The system SHALL provide a demonstration page reproducing a Liara documentation page carrying a floating rescue widget, to show where the assistant is intended to be used. The page SHALL be labelled as a demonstration and SHALL NOT present its content as real documentation.

#### Scenario: Demonstration is labelled

- **WHEN** the demonstration page is opened
- **THEN** a persistently visible notice states the content is not real documentation and links to the official site

#### Scenario: Widget invites and leads to the assistant

- **WHEN** the user hovers or focuses the widget
- **THEN** the stuck-user illustration and invitation are revealed, and activating it opens the assistant

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

### Requirement: Rescue illustrations and visible thinking state

Each rescue tool's page SHALL carry its own supplied illustration, and the stopped illustration SHALL appear where a user is actually stuck — revealed by the documentation-page widget — rather than on the assistant's own landing view. While a chat job is queued, retrieving, generating, or retrying, the interface SHALL cycle through the four supplied thinking frames at one-second intervals without replacing the job's accessible status text.

#### Scenario: Each tool page carries its illustration

- **WHEN** the Skill or MCP page is rendered
- **THEN** the corresponding illustration is present with meaningful alternative text

#### Scenario: Thinking frames continue until completion

- **WHEN** a chat job remains active
- **THEN** the visual advances to the next thinking frame every second and stops when the job completes or fails

### Requirement: Answer-level feedback

Each generated answer SHALL offer the user a helpful/unhelpful verdict, and an unhelpful verdict SHALL collect a reason from a fixed vocabulary. Submitting a verdict SHALL NOT be able to disturb the answer being read, and a verdict already recorded SHALL be shown back rather than requested again.

#### Scenario: Rejection collects an actionable reason

- **WHEN** the user marks an answer unhelpful
- **THEN** a reason is requested from a fixed set that distinguishes an incorrect answer from an incomplete, irrelevant, or wrongly sourced one

#### Scenario: Feedback failure is invisible

- **WHEN** submitting the verdict fails
- **THEN** the transcript is unaffected and no error is raised to the user

#### Scenario: A recorded verdict survives reload

- **WHEN** the conversation is reloaded after a verdict was given
- **THEN** the recorded verdict is shown instead of the prompt

### Requirement: Unbounded conversation with an abuse ceiling

A conversation SHALL NOT be cut off at a small turn limit. Turns beyond the configured verbatim window SHALL be summarized rather than dropped, invisibly to the user. A configurable ceiling SHALL remain solely to bound abuse.

#### Scenario: A fourth question is answered

- **WHEN** three user turns already exist and the user asks another question
- **THEN** the question is answered in the same conversation, with earlier turns represented by their summary

#### Scenario: The ceiling names its own cause

- **WHEN** a conversation exceeds the configured abuse ceiling
- **THEN** the refusal states that the conversation has grown too long, distinctly from any other failure
