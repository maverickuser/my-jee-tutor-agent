# Vision Diagnosis Specification

## Purpose

Defines how the tutor analyzes attempt images and produces deterministic diagnosis output.
## Requirements
### Requirement: Vision Tool Execution

The system SHALL expose a CrewAI vision tool that analyzes the preloaded invocation images and manages invocation-scoped observation state for cached replay and bounded semantic retry.

#### Scenario: Agent calls the tool without images

- **WHEN** the CrewAI agent invokes the vision analyzer with an empty JSON object
- **THEN** the tool SHALL analyze the images preloaded from the invocation

#### Scenario: No images are available

- **WHEN** the vision analyzer has no resolved images
- **THEN** it SHALL fail with a message instructing the caller to provide `image_data_uri` or `image_s3_prefix`

#### Scenario: Duplicate tool calls after valid observation

- **WHEN** the same tool instance receives duplicate calls during one invocation
- **AND** the current observation is valid
- **THEN** only the first call SHALL execute the upstream model request
- **AND** subsequent calls SHALL wait for or replay the cached result

#### Scenario: Duplicate tool calls after cached failure

- **WHEN** the same tool instance receives duplicate calls during one invocation
- **AND** the first execution failed
- **THEN** cached failures SHALL be replayed as failures

#### Scenario: Duplicate tool calls after rejected observation

- **WHEN** the current observation has been rejected by the task guardrail
- **THEN** the tool SHALL NOT replay that rejected observation
- **AND** SHALL perform one fresh vision execution only if semantic retry budget remains

### Requirement: Batched Vision Analysis

The system SHALL batch large image sets before model analysis.

#### Scenario: Image count does not exceed batch size

- **WHEN** the resolved image count is at or below the tool batch size
- **THEN** the tool SHALL issue one vision model call

#### Scenario: Image count exceeds batch size

- **WHEN** the resolved image count exceeds the tool batch size
- **THEN** the tool SHALL split images into ordered batches
- **AND** preserve expected question numbers for each batch
- **AND** merge batch outputs into one final analysis

### Requirement: Structured Diagnosis Output

The system SHALL prefer structured JSON diagnosis output for the verified diagnosis model.

#### Scenario: Structured output is enabled for the diagnosis model

- **WHEN** structured output is enabled
- **AND** the configured model is the pinned Gemini diagnosis model
- **THEN** the request SHALL include a strict JSON schema response format
- **AND** the returned JSON SHALL be validated against the diagnosis schema

#### Scenario: Structured output is enabled for an unsupported model

- **WHEN** structured output is enabled
- **AND** the configured model is not a verified Gemini model
- **AND** legacy markdown output is not enabled
- **THEN** the system SHALL reject the configuration

#### Scenario: Structured output uses an unexpected Gemini model

- **WHEN** structured output is enabled
- **AND** the configured Gemini model is not the pinned diagnosis model
- **THEN** the system SHALL reject the configuration

### Requirement: Diagnosis Schema

The system SHALL validate each diagnosis item with the required fields.

#### Scenario: A question diagnosis is returned

- **WHEN** the model returns structured diagnosis JSON
- **THEN** each question SHALL include non-blank values for `question_number`, `chapter`, `topic`, `what_you_thought`, `why_that_thought_is_wrong`, `exact_concept_gap`, and `what_you_must_deep_dive`
- **AND** unknown fields SHALL be rejected

#### Scenario: Question count mismatch

- **WHEN** the structured diagnosis question count differs from the resolved image count
- **THEN** validation SHALL fail

#### Scenario: Duplicate question numbers

- **WHEN** structured diagnosis contains duplicate readable question numbers
- **THEN** validation SHALL fail
- **AND** `Unreadable from image` SHALL not be treated as a duplicate readable number

#### Scenario: Expected question numbers are known

- **WHEN** every resolved image has an expected question number
- **THEN** structured diagnosis question numbers SHALL match the expected numbers in image order

### Requirement: Markdown Diagnosis Contract

The system SHALL render and validate diagnosis output as a Markdown table for external responses and artifacts.

#### Scenario: Markdown table is rendered

- **WHEN** structured diagnosis is accepted
- **THEN** the system SHALL render a Markdown table with the columns `Question Number`, `Chapter`, `Topic`, `What You Thought`, `Why That Thought Is Wrong`, `Exact Concept Gap`, and `What You Must Deep-Dive`

#### Scenario: Markdown output is validated

- **WHEN** Markdown analysis is validated
- **THEN** the system SHALL require the diagnosis table, separator row, required columns, at least one data row, and a row count matching resolved image count

#### Scenario: Expected question numbers are partially known

- **WHEN** only some image filenames contain question numbers
- **THEN** Markdown validation SHALL fail rather than partially matching question numbers

### Requirement: Vision Model Request Behavior

The system SHALL build stateless multimodal LiteLLM requests for vision analysis.

#### Scenario: Request construction

- **WHEN** vision analysis runs
- **THEN** the system SHALL send a system message and a user message
- **AND** the user message SHALL contain text plus one image URL part per image data URI

#### Scenario: Stateless completion

- **WHEN** completion kwargs are prepared
- **THEN** provider caching fields SHALL be disabled or removed
- **AND** LiteLLM provider retries SHALL be disabled

#### Scenario: Redacted generation observability

- **WHEN** generation input is sent to observability
- **THEN** API keys SHALL be omitted
- **AND** messages SHALL be replaced with a redaction marker because they contain image payloads

### Requirement: Vision Observation State
The vision tool SHALL track observation lifecycle state for controlled ReAct recovery.

#### Scenario: Observation is produced
- **WHEN** the vision model returns a successful observation
- **THEN** the tool state SHALL record the observation, request count, execution count, successful execution count, transport attempt count, and image count

#### Scenario: Observation is validated
- **WHEN** the task guardrail accepts an observation
- **THEN** the tool state SHALL allow cached replay of that valid observation

#### Scenario: Observation is rejected
- **WHEN** the task guardrail rejects an observation for semantic reasons
- **THEN** the tool state SHALL record observation rejected, rejection category, semantic retry count, and remaining semantic retry budget

#### Scenario: Observation is replaced
- **WHEN** a semantic retry produces a new successful observation
- **THEN** the tool state SHALL replace the rejected observation
- **AND** emit observation-replaced telemetry

### Requirement: Guardrail Approved Rendering Input
The vision diagnosis workflow SHALL render only task-guardrail-approved structured output for the CrewAI/ReAct path.

#### Scenario: Task guardrail passes
- **WHEN** the CrewAI task guardrail approves structured JSON output
- **THEN** post-workflow code MAY parse the approved JSON and render Markdown deterministically
- **AND** SHALL NOT repeat the same task-output correctness checks as an additional gate

#### Scenario: Task guardrail fails
- **WHEN** the CrewAI task guardrail fails after allowed retry handling
- **THEN** the workflow SHALL fail before Markdown rendering
- **AND** no response or artifact SHALL be built from unapproved output

### Requirement: Vision Diagnosis Adapter Boundary
The system SHALL keep CrewAI and LiteLLM details behind vision diagnosis adapters.

#### Scenario: Vision diagnosis application runs
- **WHEN** the diagnosis workflow analyzes resolved images
- **THEN** batching, expected-question-number preservation, semantic retry decisions, and diagnosis validation SHALL be coordinated by application or domain code
- **AND** CrewAI tool classes and LiteLLM request construction SHALL remain adapter concerns

#### Scenario: CrewAI adapter invokes vision diagnosis
- **WHEN** CrewAI requests image analysis through the vision tool
- **THEN** the CrewAI adapter SHALL call the vision diagnosis application interface
- **AND** duplicate-call caching and failure replay behavior SHALL remain compatible with the existing vision tool execution requirements
