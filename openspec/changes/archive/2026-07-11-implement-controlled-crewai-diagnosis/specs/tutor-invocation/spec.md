## MODIFIED Requirements

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

## ADDED Requirements

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
