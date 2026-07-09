## ADDED Requirements

### Requirement: Controlled ReAct Role
The system SHALL use CrewAI ReAct only for bounded orchestration and recovery around the approved vision analyzer tool.

#### Scenario: ReAct runs the diagnosis task
- **WHEN** the diagnosis task executes through CrewAI
- **THEN** the agent SHALL use `jee_question_vision_analyzer` for image diagnosis
- **AND** SHALL NOT diagnose image content independently from the tool observation
- **AND** SHALL NOT call unapproved tools, create artifacts, send email, or perform safety moderation

#### Scenario: Tool observation is valid and final output is valid
- **WHEN** the vision tool returns a valid structured observation
- **AND** the CrewAI final output canonically matches that observation
- **THEN** the task SHALL pass without a guardrail retry

### Requirement: Finalization Retry
The system SHALL allow one cached finalization retry when the tool observation is valid but CrewAI final output is malformed or modified.

#### Scenario: Final output is not JSON
- **WHEN** the vision tool observation is valid
- **AND** the CrewAI final output is Markdown, prose, a code fence, or otherwise not a JSON object
- **THEN** the task guardrail SHALL return retry feedback telling CrewAI to return exactly the JSON observation
- **AND** a repeated vision tool call SHALL replay the cached valid observation
- **AND** real vision execution count SHALL NOT increase

#### Scenario: Final output differs from valid observation
- **WHEN** the CrewAI final output is valid JSON
- **AND** it differs from the valid tool observation after canonical JSON normalization
- **THEN** the task guardrail SHALL return `VALIDATION_ERROR: canonical_mismatch`
- **AND** a repeated vision tool call SHALL replay the cached valid observation

### Requirement: Semantic Vision Retry
The system SHALL allow one fresh semantic vision retry when the tool observation itself is invalid for the current invocation.

#### Scenario: Tool observation is semantically invalid
- **WHEN** the tool observation is invalid JSON, violates the diagnosis schema, has the wrong question count, mismatches expected question numbers, contains duplicate readable question numbers, or fails taxonomy validation
- **THEN** the guardrail SHALL mark the observation rejected
- **AND** the tool SHALL NOT replay the rejected observation
- **AND** the next tool call MAY perform one fresh vision execution if semantic retry budget remains

#### Scenario: Second observation succeeds
- **WHEN** a semantic retry produces a valid observation
- **THEN** the new observation SHALL replace the rejected observation
- **AND** the task MAY pass if the final output canonically matches the new observation

#### Scenario: Semantic retry is exhausted
- **WHEN** the semantic retry budget is exhausted
- **THEN** the workflow SHALL fail
- **AND** the rejected observation SHALL NOT be replayed
- **AND** rendering, Bedrock output guardrail, artifact creation, email delivery, and successful response formatting SHALL NOT run

### Requirement: ReAct Call Budgets
The system SHALL keep CrewAI orchestration and vision execution bounded.

#### Scenario: Guardrail retry budget
- **WHEN** the diagnosis task is built
- **THEN** CrewAI task guardrail retries SHALL be capped at one retry

#### Scenario: Vision execution budget
- **WHEN** one invocation runs
- **THEN** real vision executions SHALL be capped at two
- **AND** the second execution SHALL occur only for semantic vision retry

#### Scenario: Orchestration budget is exceeded
- **WHEN** CrewAI exceeds the configured orchestration call budget
- **THEN** the workflow SHALL fail safely
- **AND** emit budget-exceeded telemetry

### Requirement: Controlled ReAct Telemetry
The system SHALL emit telemetry that distinguishes tool requests, cached replay, real executions, retries, and exhausted retry paths.

#### Scenario: Finalization retry telemetry
- **WHEN** a finalization retry occurs
- **THEN** telemetry SHALL identify `cached_finalization_retry`
- **AND** show that request count may increase while real execution count does not

#### Scenario: Semantic retry telemetry
- **WHEN** a semantic vision retry occurs
- **THEN** telemetry SHALL identify `semantic_vision_retry`
- **AND** include observation rejected and observation replaced counters when applicable
