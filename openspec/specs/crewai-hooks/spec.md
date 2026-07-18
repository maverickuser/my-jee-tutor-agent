# crewai-hooks Specification

## Purpose
TBD - created by archiving change implement-controlled-crewai-diagnosis. Update Purpose after archive.
## Requirements
### Requirement: CrewAI Callback Bundle
The system SHALL provide a CrewAI callback factory for lifecycle observability.

#### Scenario: Callback bundle is built
- **WHEN** callback context includes invocation id, expected image count, expected question numbers, tool call state, and optional status store
- **THEN** the factory SHALL return before-kickoff callbacks, after-kickoff callbacks, and a task callback
- **AND** SHALL NOT wire `step_callback` in the initial implementation

### Requirement: Before Kickoff Callback
The system SHALL record safe CrewAI start metadata before kickoff.

#### Scenario: CrewAI kickoff starts
- **WHEN** the before-kickoff callback runs
- **THEN** it SHALL log invocation id, expected image count, expected question number count, ReAct mode, and crew/task/agent names when available
- **AND** MAY write a safe status-store event
- **AND** SHALL NOT parse raw payloads, list S3 objects, decode image payloads, call Bedrock Guardrails, mutate output, or validate final output

### Requirement: After Kickoff Callback
The system SHALL record safe CrewAI completion metadata after kickoff.

#### Scenario: CrewAI kickoff finishes
- **WHEN** the after-kickoff callback runs
- **THEN** it SHALL log completion status, output size metadata, tool request count, tool execution count, tool success or failure state, task guardrail metadata when available, and orchestration call count when available
- **AND** MAY write a safe status-store event
- **AND** SHALL NOT fix output, retry workflow, validate final output, create artifacts, or send email

### Requirement: Task Callback
The system SHALL record safe task-level completion metadata.

#### Scenario: Diagnosis task completes
- **WHEN** the task callback runs
- **THEN** it SHALL log task name, elapsed time when available, output length, and task guardrail pass or fail metadata when available
- **AND** SHALL NOT log full task output or full diagnosis JSON

### Requirement: Hook Failure Policy
The system SHALL treat hook failures as observability failures unless required prepared metadata is missing.

#### Scenario: Optional telemetry fails
- **WHEN** logging or status-store writing inside a hook fails
- **THEN** diagnosis SHALL continue
- **AND** the hook failure SHALL be logged safely

#### Scenario: Required metadata is missing
- **WHEN** required invocation-prepared metadata is missing before kickoff
- **THEN** the hook MAY fail before diagnosis because this indicates a programming or configuration error

### Requirement: Hook Privacy
CrewAI hooks SHALL only emit safe metadata.

#### Scenario: Hook logs are emitted
- **WHEN** any CrewAI hook logs or records telemetry
- **THEN** it SHALL NOT include image data URIs, base64 image payloads, full model output, full diagnosis JSON, full invalid output, or recipient email
