## ADDED Requirements

### Requirement: Deterministic Diagnosis Task Guardrail
The system SHALL attach a deterministic Python guardrail to the CrewAI diagnosis task.

#### Scenario: Diagnosis task is built
- **WHEN** `build_diagnosis_task` creates the CrewAI task
- **THEN** the task SHALL include a guardrail built from invocation-scoped tool state, expected image count, and expected question numbers
- **AND** the task SHALL set `max_retries` to one

#### Scenario: Guardrail implementation
- **WHEN** the guardrail checks task output
- **THEN** it SHALL use deterministic code
- **AND** SHALL NOT call an LLM, S3, SES, DynamoDB, Bedrock Guardrails, artifact writers, or email delivery

### Requirement: Task Output Contract
The task guardrail SHALL validate that CrewAI final output exactly represents the approved vision tool observation.

#### Scenario: Output is empty
- **WHEN** task output is missing or empty
- **THEN** the guardrail SHALL fail with `Diagnosis task returned empty output.`

#### Scenario: Tool observation is missing
- **WHEN** the vision tool did not produce a successful observation
- **THEN** the guardrail SHALL fail with `Diagnosis task completed without a successful vision tool observation.`

#### Scenario: Output is not a JSON object
- **WHEN** task output does not start as a JSON object
- **THEN** the guardrail SHALL fail with `VALIDATION_ERROR: non_json_output`
- **AND** tell CrewAI to return exactly the JSON observation from `jee_question_vision_analyzer`

#### Scenario: Output changes the tool observation
- **WHEN** task output and tool observation are both parseable JSON
- **AND** their canonical JSON forms differ
- **THEN** the guardrail SHALL fail with `VALIDATION_ERROR: canonical_mismatch`

### Requirement: Structured Diagnosis Validation
The task guardrail SHALL validate the structured diagnosis schema and invocation shape.

#### Scenario: Schema validation fails
- **WHEN** final output or tool observation does not match the structured diagnosis schema
- **THEN** the guardrail SHALL fail with a safe schema validation summary
- **AND** SHALL NOT include the full invalid output

#### Scenario: Image count mismatches
- **WHEN** diagnosis question count differs from expected image count
- **THEN** the guardrail SHALL fail with a question-count mismatch category

#### Scenario: Expected question numbers mismatch
- **WHEN** expected question numbers are available for all images
- **AND** diagnosis question numbers do not match image order
- **THEN** the guardrail SHALL fail with a question-number mismatch category

#### Scenario: Duplicate readable question numbers
- **WHEN** diagnosis output contains duplicate readable question numbers
- **THEN** the guardrail SHALL fail with a duplicate-question category

### Requirement: Guardrail Failure Classification
The task guardrail SHALL classify failures into retry categories.

#### Scenario: Finalization failure
- **WHEN** the tool observation is valid
- **AND** final output is malformed or canonically mismatched
- **THEN** the guardrail SHALL classify the failure as `cached_finalization_retry`

#### Scenario: Semantic observation failure
- **WHEN** the tool observation itself is invalid for schema, count, question-number, duplicate, or taxonomy reasons
- **THEN** the guardrail SHALL classify the failure as `semantic_vision_retry`
- **AND** mark the observation rejected when retry budget remains

#### Scenario: Non-retryable failure
- **WHEN** no useful ReAct recovery exists
- **THEN** the guardrail SHALL classify the failure as `non_retryable`

### Requirement: Guardrail Observability
The task guardrail SHALL emit safe structured telemetry for every check.

#### Scenario: Guardrail check runs
- **WHEN** the guardrail evaluates task output
- **THEN** telemetry SHALL include invocation id when available, task name, guardrail name, result, expected image count, expected question number count, tool call counters, tool success, observation presence, retry category, and failure category when failed
- **AND** SHALL NOT log image payloads, full diagnosis JSON, full invalid output, or recipient email

#### Scenario: Guardrail coverage is measured
- **WHEN** CrewAI diagnosis tasks complete
- **THEN** telemetry SHALL support measuring guardrail execution rate and attempts per task
- **AND** attempts per task SHALL be at most two
