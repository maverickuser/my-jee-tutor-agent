## ADDED Requirements

### Requirement: Taxonomy Source
The system SHALL use an approved normalized taxonomy artifact as the runtime source of truth for chapter/topic validation.

#### Scenario: S3 taxonomy is configured
- **WHEN** `CURRICULUM_TAXONOMY_S3_URI` is set
- **THEN** the runtime SHALL load the approved taxonomy JSON from S3
- **AND** SHALL NOT parse source PDFs during invocation handling

#### Scenario: Local taxonomy is configured
- **WHEN** no S3 taxonomy URI is set
- **AND** `CURRICULUM_TAXONOMY_LOCAL_PATH` is set
- **THEN** the runtime SHALL load the approved taxonomy JSON from the local path

#### Scenario: No taxonomy source is configured
- **WHEN** no taxonomy source is configured
- **AND** taxonomy is required
- **THEN** curriculum validation SHALL fail closed with `taxonomy_unavailable`
- **AND** when taxonomy is not required, validation SHALL be disabled with safe telemetry

### Requirement: Taxonomy Artifact Schema
The taxonomy artifact SHALL define versioned subjects, chapters, topics, and aliases.

#### Scenario: Taxonomy is parsed
- **WHEN** taxonomy JSON is loaded
- **THEN** it SHALL include `version`, `source_documents`, and `subjects`
- **AND** each subject SHALL contain chapters
- **AND** each chapter SHALL contain topics
- **AND** chapters and topics MAY contain aliases

#### Scenario: Taxonomy is malformed
- **WHEN** taxonomy JSON is invalid, unsupported, or semantically empty
- **THEN** loading SHALL fail with `taxonomy_invalid`

### Requirement: Taxonomy Cache
The system SHALL cache parsed taxonomy data in process memory.

#### Scenario: Cache TTL has not expired
- **WHEN** a valid taxonomy is cached before TTL expiry
- **THEN** validation SHALL use the cached taxonomy without re-reading the source

#### Scenario: S3 cache TTL expires and ETag is unchanged
- **WHEN** the cache TTL expires
- **AND** S3 `HeadObject` reports the same ETag
- **THEN** the loader SHALL extend the cache TTL without fetching and reparsing the object

#### Scenario: S3 cache TTL expires and ETag changed
- **WHEN** the cache TTL expires
- **AND** S3 ETag changed
- **THEN** the loader SHALL fetch, parse, validate, and atomically swap in the new taxonomy

#### Scenario: Reload fails after a valid cache exists
- **WHEN** taxonomy reload fails
- **AND** a prior valid taxonomy is cached
- **THEN** validation SHALL keep using the cached taxonomy
- **AND** emit reload-failure telemetry

### Requirement: Chapter Topic Validation
The system SHALL deterministically validate diagnosis chapter/topic labels against the taxonomy.

#### Scenario: Canonical labels match
- **WHEN** a diagnosis chapter and topic match approved canonical taxonomy labels after normalization
- **THEN** curriculum validation SHALL pass for that diagnosis item

#### Scenario: Alias labels match
- **WHEN** a diagnosis chapter or topic matches an approved alias after normalization
- **THEN** curriculum validation SHALL pass using the canonical taxonomy path

#### Scenario: Unknown chapter
- **WHEN** a diagnosis chapter does not match an approved chapter or alias
- **THEN** validation SHALL fail with `unknown_chapter`

#### Scenario: Unknown topic
- **WHEN** a diagnosis topic does not match an approved topic or alias
- **THEN** validation SHALL fail with `unknown_topic`

#### Scenario: Topic belongs to a different chapter
- **WHEN** the topic is approved but not under the resolved chapter
- **THEN** validation SHALL fail with `topic_not_in_chapter`

#### Scenario: Ambiguous taxonomy path
- **WHEN** chapter/topic labels resolve to multiple taxonomy paths
- **THEN** validation SHALL fail with `ambiguous_chapter_topic`

#### Scenario: Both labels are unable to determine
- **WHEN** both chapter and topic equal `Unable to determine from image`
- **THEN** validation SHALL pass for that item
- **AND** emit low-confidence observation telemetry

#### Scenario: One label is unable to determine
- **WHEN** only one of chapter or topic equals `Unable to determine from image`
- **THEN** validation SHALL fail with `partial_curriculum_label`

### Requirement: Task Guardrail Integration
The task guardrail SHALL include curriculum validation after structured diagnosis and invocation-shape checks.

#### Scenario: Taxonomy mismatch occurs
- **WHEN** diagnosis output passes JSON, schema, image count, and question-number checks
- **AND** chapter/topic taxonomy validation fails
- **THEN** the task guardrail SHALL classify the failure as semantic vision retry
- **AND** mark the current observation rejected
- **AND** return safe feedback that does not include the full taxonomy

#### Scenario: Second taxonomy mismatch occurs
- **WHEN** a semantic retry observation also fails taxonomy validation
- **THEN** the workflow SHALL fail
- **AND** rendering, Bedrock output guardrail, artifacts, email, and successful response SHALL NOT run

#### Scenario: Markdown output remains supported
- **WHEN** a non-CrewAI path supports Markdown output
- **THEN** Markdown SHALL be parsed into the same diagnosis model before curriculum validation
- **AND** SHALL NOT bypass deterministic curriculum validation

### Requirement: Taxonomy Generation Job
The system SHALL provide a separate explicitly triggered job to generate taxonomy JSON from source PDFs.

#### Scenario: Generation job runs
- **WHEN** source PDF S3 URIs, output S3 URI, taxonomy version, and publish flag are provided
- **THEN** the job SHALL download the explicitly supplied PDFs, extract candidate labels, validate the draft taxonomy schema, run deterministic sanity checks, produce a diff against the current approved taxonomy when available, and store generated JSON as a pipeline artifact

#### Scenario: Publish is not approved
- **WHEN** `PUBLISH_TAXONOMY` is false
- **THEN** the job SHALL NOT write the approved taxonomy output S3 URI

#### Scenario: Publish is approved
- **WHEN** `PUBLISH_TAXONOMY` is true
- **AND** schema validation and sanity checks pass
- **THEN** the job MAY publish the approved taxonomy JSON to `CURRICULUM_TAXONOMY_OUTPUT_S3_URI`

#### Scenario: Generation inputs are invalid
- **WHEN** source PDFs are missing, malformed, unreadable, empty, or produce an invalid taxonomy
- **THEN** the job SHALL fail
- **AND** SHALL NOT publish an approved taxonomy
