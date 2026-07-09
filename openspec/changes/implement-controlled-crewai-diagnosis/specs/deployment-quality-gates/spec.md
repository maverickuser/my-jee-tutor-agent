## ADDED Requirements

### Requirement: Controlled ReAct CI Gate
CI SHALL verify controlled ReAct orchestration behavior.

#### Scenario: Controlled ReAct tests run
- **WHEN** CI executes the test suite
- **THEN** tests SHALL prove the first ReAct attempt calls the vision tool
- **AND** valid observation plus valid final output passes without retry
- **AND** malformed final output triggers cached finalization retry
- **AND** cached finalization retry does not increase real vision execution count

#### Scenario: Semantic retry tests run
- **WHEN** CI executes the test suite
- **THEN** tests SHALL prove invalid observations trigger one semantic vision retry
- **AND** rejected observations are not replayed
- **AND** a second valid observation replaces the rejected observation
- **AND** a second invalid observation fails the workflow

#### Scenario: Safety boundary tests run
- **WHEN** CI executes the test suite
- **THEN** tests SHALL prove artifacts, email delivery, Bedrock output guardrail, and successful responses only happen after task guardrail approval

### Requirement: CrewAI Hook CI Gate
CI SHALL verify CrewAI lifecycle hooks are wired safely.

#### Scenario: Hook wiring tests run
- **WHEN** CI executes the test suite
- **THEN** tests SHALL prove before-kickoff callbacks, after-kickoff callbacks, and task callback are wired
- **AND** `step_callback` is not wired in the initial implementation

#### Scenario: Hook privacy tests run
- **WHEN** hook tests inspect emitted logs or telemetry
- **THEN** they SHALL prove hooks do not emit image payloads, recipient email, full diagnosis JSON, or full invalid output

### Requirement: Task Guardrail CI Gate
CI SHALL verify deterministic task guardrail behavior.

#### Scenario: Guardrail contract tests run
- **WHEN** CI executes task guardrail tests
- **THEN** tests SHALL cover empty output, missing tool observation, non-JSON output, canonical mismatch, schema invalid output, question-count mismatch, question-number mismatch, duplicate question numbers, and valid output

#### Scenario: Guardrail metric tests run
- **WHEN** CI executes task guardrail tests
- **THEN** tests SHALL prove guardrail check telemetry is emitted without full output payloads

### Requirement: Curriculum Taxonomy CI Gate
CI SHALL verify deterministic taxonomy loading, validation, and generation controls.

#### Scenario: Taxonomy validation tests run
- **WHEN** CI executes taxonomy tests
- **THEN** tests SHALL cover canonical matches, aliases, unknown chapter, unknown topic, topic under wrong chapter, ambiguous paths, sentinel handling, fail-closed missing taxonomy, and fail-open disabled taxonomy

#### Scenario: Taxonomy cache tests run
- **WHEN** CI executes taxonomy loader tests
- **THEN** tests SHALL prove cached taxonomy is used before TTL expiry
- **AND** S3 taxonomy reloads when ETag changes
- **AND** a prior valid cache remains in use when reload fails

#### Scenario: Taxonomy generation tests run
- **WHEN** CI executes taxonomy generation tests
- **THEN** tests SHALL prove missing source PDFs fail the job
- **AND** draft taxonomy schema is validated before publish
- **AND** publish does not occur unless explicitly approved

### Requirement: Deployment Evidence
Deployment quality reporting SHALL preserve evidence for guardrail, retry, and taxonomy behavior.

#### Scenario: CD reports are produced
- **WHEN** deployment evals and security gates run
- **THEN** reports SHALL include aggregate evidence for CrewAI guardrail pass/fail, retry categories, vision execution caps, artifact safety counters, taxonomy validation pass/failure, and taxonomy version/source when configured

#### Scenario: Langfuse credentials are configured
- **WHEN** deployment quality gates publish aggregate metrics
- **THEN** Langfuse metrics SHALL include controlled ReAct, task guardrail, taxonomy, eval, and garak summaries without image payloads or raw recipient emails
