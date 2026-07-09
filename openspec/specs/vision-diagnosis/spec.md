# Vision Diagnosis Specification

## Purpose

Defines how the tutor analyzes attempt images and produces deterministic diagnosis output.

## Requirements

### Requirement: Vision Tool Execution

The system SHALL expose a CrewAI vision tool that analyzes the preloaded invocation images.

#### Scenario: Agent calls the tool without images

- **WHEN** the CrewAI agent invokes the vision analyzer with an empty JSON object
- **THEN** the tool SHALL analyze the images preloaded from the invocation

#### Scenario: No images are available

- **WHEN** the vision analyzer has no resolved images
- **THEN** it SHALL fail with a message instructing the caller to provide `image_data_uri` or `image_s3_prefix`

#### Scenario: Duplicate tool calls

- **WHEN** the same tool instance receives duplicate calls during one invocation
- **THEN** only the first call SHALL execute the upstream model request
- **AND** subsequent calls SHALL wait for or replay the cached result
- **AND** cached failures SHALL be replayed as failures

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
