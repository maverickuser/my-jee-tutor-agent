# Tutor Invocation Specification

## Purpose

Defines the external invocation contract and lifecycle for the JEE tutor runtime.
## Requirements
### Requirement: Payload Validation

The system SHALL validate tutor invocations with a strict payload schema.

#### Scenario: Exactly one image source is provided

- **WHEN** the caller sends either `image_data_uri` or `image_s3_prefix`
- **THEN** the request is valid with respect to image source selection
- **AND** the system SHALL reject requests that provide both fields
- **AND** the system SHALL reject requests that provide neither field
- **AND** the system SHALL reject unknown payload fields

#### Scenario: Recipient email is provided

- **WHEN** `recipient_email` is present
- **THEN** the system SHALL trim and validate it as a non-blank email-like value
- **AND** the system SHALL require `image_s3_prefix`
- **AND** the system SHALL reject requests that request email with only `image_data_uri`

#### Scenario: Safe trace input is emitted

- **WHEN** invocation input is passed to observability
- **THEN** the system SHALL omit `image_data_uri`
- **AND** the system SHALL omit `recipient_email`

### Requirement: Image Input Resolution

The system SHALL normalize supported invocation image inputs into image data URIs before running the tutor workflow.

#### Scenario: Direct image data URI

- **WHEN** `image_data_uri` is provided
- **THEN** the resolver SHALL return that image as the only resolved image

#### Scenario: S3 prefix input

- **WHEN** `image_s3_prefix` is provided
- **THEN** the resolver SHALL parse the value as an S3 URI
- **AND** list non-folder objects under the prefix
- **AND** load supported image objects as data URIs
- **AND** support `.jpg`, `.jpeg`, `.png`, and `.webp`
- **AND** reject prefixes with no supported images

#### Scenario: Ordered S3 images

- **WHEN** multiple supported S3 images are found
- **THEN** images with numeric filename stems SHALL be ordered by extracted question number first
- **AND** images without extracted question numbers SHALL be ordered after numbered images by key
- **AND** extracted question numbers SHALL be passed to the workflow as expected question numbers

### Requirement: Idempotency

The system SHALL provide process-local idempotency for requests that include `idempotency_key`.

#### Scenario: First request for a key

- **WHEN** a valid request uses an unused `idempotency_key`
- **THEN** the system SHALL acquire the key and process the invocation

#### Scenario: Duplicate completed request

- **WHEN** a request repeats the same key and same normalized payload within the idempotency TTL
- **AND** the first request has completed
- **THEN** the system SHALL return the cached response
- **AND** record the invocation status as `REPLAYED`

#### Scenario: Concurrent duplicate request

- **WHEN** a request repeats the same key and same normalized payload while the first request is still running
- **THEN** the system SHALL return an error indicating the invocation is already in progress
- **AND** record the invocation status as `BLOCKED`

#### Scenario: Key reuse with different payload

- **WHEN** a request repeats an idempotency key with a different normalized payload within the TTL
- **THEN** the system SHALL reject the request as an idempotency conflict
- **AND** tell the caller to use a new key

### Requirement: Invocation Status Recording

The system SHALL record invocation lifecycle status, CrewAI guardrail/retry lifecycle, and nested LLM-call telemetry when a status store is configured.

#### Scenario: Status store disabled

- **WHEN** no invocation status table is configured
- **THEN** status recording SHALL be a no-op
- **AND** invocation handling SHALL continue

#### Scenario: Status store enabled

- **WHEN** `INVOCATION_STATUS_TABLE_NAME` is configured and status recording is enabled
- **THEN** the system SHALL write status records to DynamoDB
- **AND** include invocation id, status, timestamps, subject, image count, optional idempotency key, optional runtime commit SHA, artifact URI, email fields, error fields, CrewAI lifecycle metadata, guardrail retry metadata, and nested LLM-call telemetry when known

#### Scenario: Workflow lifecycle

- **WHEN** an invocation is handled
- **THEN** the system SHALL record `RECEIVED` after payload validation
- **AND** record `VALIDATED` after idempotency and schema validation pass
- **AND** record `IN_PROGRESS` before vision analysis
- **AND** record `SUCCEEDED`, `FAILED`, `BLOCKED`, or `REPLAYED` as the terminal status

#### Scenario: CrewAI lifecycle is observed

- **WHEN** CrewAI kickoff starts, kickoff completes, or the diagnosis task completes
- **THEN** the system SHALL record safe lifecycle telemetry when status recording is configured
- **AND** SHALL NOT store image payloads, full diagnosis output, full invalid output, stack traces, or raw recipient email in lifecycle telemetry

#### Scenario: LLM call history is recorded

- **WHEN** vision analysis runs in one or more batches
- **THEN** the system SHALL append nested LLM call records with call id, batch index, batch size, model, provider, purpose, status, attempt number, timestamps, duration, optional token counts, optional error fields, and optional safe response summary
- **AND** SHALL NOT store full LLM response bodies

### Requirement: Response Shape

The system SHALL return JSON-compatible response dictionaries.

#### Scenario: Successful analysis

- **WHEN** the workflow completes
- **THEN** the response SHALL include `analysis`
- **AND** include artifact and email metadata only when applicable
- **AND** include `runtime_commit_sha` when `JEE_TUTOR_GIT_SHA` is set to a value other than `unknown`

#### Scenario: Error response

- **WHEN** validation, input resolution, guardrail, or workflow handling fails in a handled path
- **THEN** the response SHALL include `error`
- **AND** include a `details` list
- **AND** include `runtime_commit_sha` when available

### Requirement: Guardrail Approved Invocation Success
The invocation layer SHALL only produce successful analysis responses after the CrewAI task-output guardrail has passed for the CrewAI/ReAct path.

#### Scenario: Guardrail approved output
- **WHEN** the CrewAI task guardrail passes
- **THEN** the invocation MAY continue to Bedrock output guardrail checks, artifact writing, email delivery, status completion, and success response formatting

#### Scenario: Guardrail rejected output
- **WHEN** the CrewAI task guardrail fails after allowed retry handling
- **THEN** the invocation SHALL return a handled workflow error
- **AND** SHALL record terminal failure status
- **AND** SHALL NOT run Bedrock output guardrail, artifact writing, email delivery, or success response formatting

### Requirement: Status Privacy
The status store SHALL avoid storing sensitive or bulky payloads.

#### Scenario: Status fields are persisted
- **WHEN** invocation, CrewAI, guardrail, or LLM-call telemetry is written
- **THEN** the system SHALL keep status reasons and error messages short
- **AND** SHALL NOT persist raw image data URIs, base64 payloads, full model responses, full invalid output, stack traces, or raw sensitive values detected by guardrails

### Requirement: Invocation Application Boundary
The system SHALL route tutor invocation orchestration through an application service that depends on explicit ports for external effects.

#### Scenario: Invocation service uses ports
- **WHEN** a tutor invocation is handled
- **THEN** image resolution, guardrail checks, workflow execution, artifact writing, email coordination, idempotency, status recording, and observability SHALL be accessed through injected interfaces or application collaborators
- **AND** the invocation behavior SHALL remain compatible with the existing payload validation, idempotency, status recording, and response shape requirements

#### Scenario: Handler delegates to composition
- **WHEN** the runtime handler receives an invocation event
- **THEN** it SHALL delegate to the configured invocation application service
- **AND** it SHALL NOT directly construct vendor-specific clients outside the composition path
