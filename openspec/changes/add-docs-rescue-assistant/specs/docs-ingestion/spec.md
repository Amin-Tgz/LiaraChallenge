## Purpose

Turns Liara's public documentation repository into a versioned, queryable index — parsing MDX that stores its section headings as JSX components, preserving citation anchors and images, and activating each new index only after validation so a failed run never degrades the running system.

## ADDED Requirements

### Requirement: Source acquisition and change detection

The system SHALL fetch the configured documentation repository and record the exact commit SHA of the content it indexed. It SHALL detect added, modified, and deleted files relative to the currently active index and reindex only what changed.

#### Scenario: First ingestion

- **WHEN** ingestion runs with no active index present
- **THEN** every in-scope document is parsed, embedded, and stored, and the resulting index records the source commit SHA

#### Scenario: No upstream change

- **WHEN** ingestion runs and the upstream commit SHA matches the active index
- **THEN** the run exits without generating embeddings and reports that no change was detected

#### Scenario: Incremental change

- **WHEN** ingestion runs and a subset of documents changed upstream
- **THEN** only added and modified documents are re-embedded, deleted documents are removed from the new index, and unchanged documents are carried forward

### Requirement: Ingestion scope is configuration

The system SHALL determine which documentation sections to ingest from configuration. Changing scope SHALL NOT require code changes.

#### Scenario: Narrowed scope

- **WHEN** the configured section list names a subset of sections
- **THEN** only documents under those sections are indexed and documents outside them are absent from retrieval results

### Requirement: JSX pre-pass produces clean Markdown

The source documents are MDX containing import statements, wrapper components, JSX expression blocks, and section headings expressed as `<Section id title />` components rather than Markdown headings. The system SHALL convert these into clean Markdown before parsing, matching on JSX tag names rather than import paths.

#### Scenario: Section component becomes a heading

- **WHEN** a document contains `<Section id="envs" title="متغیرهای محیطی" />`
- **THEN** the extracted content contains a heading with text `متغیرهای محیطی` and records `envs` as that section's anchor

#### Scenario: Non-content constructs removed

- **WHEN** a document contains import statements, a `<Layout>` wrapper, a `<Head>` block, JSX expression blocks, or navigation-only components
- **THEN** none of their markup appears in the text submitted for embedding

#### Scenario: Inline links preserved

- **WHEN** a document contains an inline anchor element with an href and styling attributes
- **THEN** the link target and its text are preserved in the extracted Markdown and the styling attributes are discarded

#### Scenario: Inconsistent import paths tolerated

- **WHEN** two documents import the same component from different module paths
- **THEN** both documents' occurrences of that component are transformed identically

#### Scenario: Unrecognized markup is measurable

- **WHEN** a document is processed
- **THEN** the proportion of source characters discarded is recorded, and documents exceeding the configured threshold are reported for review

### Requirement: Section-aware chunking

The system SHALL split documents at section boundaries, preserving semantic units so that retrieved evidence is independently meaningful.

#### Scenario: Code stays with its explanation

- **WHEN** a section contains a code block preceded or followed by explanatory prose
- **THEN** the code block and that adjacent prose occupy the same chunk

#### Scenario: Steps stay with their images

- **WHEN** a section contains a step and an image belonging to that step
- **THEN** both remain in the same chunk

#### Scenario: No meaningless fragments

- **WHEN** chunking produces a candidate below the configured minimum size or lacking standalone meaning
- **THEN** that candidate is merged with an adjacent chunk rather than stored alone

### Requirement: Chunk metadata and citation anchors

Every stored chunk SHALL carry metadata sufficient to cite it precisely and to filter or boost it during retrieval, including document identity, section title, breadcrumbs, service, runtime, framework, content type, language, code languages, source path, source URL, source commit, heading anchor, associated images, and the embedding dimension used.

#### Scenario: Deep-linkable citation

- **WHEN** a chunk derived from a section with a known anchor is retrieved
- **THEN** its citation resolves to the document's public URL combined with that section anchor

#### Scenario: Image association

- **WHEN** a chunk's source section contains an image
- **THEN** the image URL, alt text, and position are stored in that chunk's metadata, and the alt text plus surrounding instructional text are included in the text submitted for embedding

### Requirement: Embedding generation

The system SHALL generate embeddings in batches at the configured dimensionality and record that dimensionality in the index metadata.

#### Scenario: Dimension recorded

- **WHEN** an index version is created
- **THEN** the embedding model identifier and vector dimension used are stored with it

#### Scenario: Batch failure does not corrupt the index

- **WHEN** an embedding batch fails after its permitted retries
- **THEN** the new index version is not activated and the previously active index remains in service

### Requirement: Versioned index activation with rollback

The system SHALL NOT modify an active index in place. It SHALL build a new index version, validate it, activate it atomically, and retain at least one prior healthy version.

#### Scenario: Validation gate

- **WHEN** a newly built index fails its validation checks
- **THEN** it is not activated, the previous index continues serving, and the failure is recorded with a distinct error code

#### Scenario: Atomic activation

- **WHEN** a validated index version is activated
- **THEN** retrieval requests observe either entirely the previous version or entirely the new one, never a mixture

#### Scenario: Rollback available

- **WHEN** an activated index is found to be faulty and a prior healthy version exists
- **THEN** the prior version can be reactivated without re-running ingestion
