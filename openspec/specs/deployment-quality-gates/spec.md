# Deployment Quality Gates Specification

## Purpose

Defines deployment, evaluation, and security quality gates for the AgentCore runtime.
## Requirements
### Requirement: Infrastructure Provisioning

The system SHALL provision the runtime infrastructure with Terraform.

#### Scenario: Terraform deployment runs

- **WHEN** deployment is executed
- **THEN** Terraform SHALL manage the ECR repository, AgentCore execution role, AgentCore runtime, default runtime endpoint, CloudWatch log group, optional Bedrock Guardrail, S3 image input permissions, invocation status storage, and email delivery resources

#### Scenario: Runtime image is deployed

- **WHEN** the container image is built and pushed
- **THEN** deployment SHALL pass the pushed image URI into Terraform as the AgentCore runtime image

### Requirement: Runtime Environment Configuration

The deployment SHALL configure runtime environment needed by the application.

#### Scenario: Model and provider configuration is supplied

- **WHEN** runtime environment variables are configured
- **THEN** the runtime SHALL be able to resolve model, LiteLLM, Bedrock, AWS, Langfuse, guardrail, invocation status, and email settings from environment or config file values

#### Scenario: Commit SHA is supplied

- **WHEN** `JEE_TUTOR_GIT_SHA` is configured to a value other than `unknown`
- **THEN** invocation responses and status records SHALL include that runtime commit SHA

### Requirement: Continuous Integration

The repository SHALL enforce static checks and unit test coverage in CI.

#### Scenario: CI test job runs

- **WHEN** CI executes
- **THEN** it SHALL install dependencies
- **AND** run Ruff
- **AND** run the unit test suite with coverage
- **AND** enforce the configured coverage threshold

### Requirement: Agent Evaluation Gate

Deployment SHALL run agent evaluations against the runtime handler.

#### Scenario: CD evals run

- **WHEN** deployment quality gates execute
- **THEN** the eval runner SHALL read cases from `evals/jee_tutor_eval_cases.json`
- **AND** invoke the same handler path used by AgentCore
- **AND** use the configured S3 eval image prefix
- **AND** write `eval_runs/agent-evals.json`

#### Scenario: Eval score is below threshold

- **WHEN** the eval pass rate is below `CD_EVAL_MIN_SCORE`
- **THEN** the deployment quality gate SHALL fail

### Requirement: Deployed Runtime Smoke Gate

Deployment SHALL smoke test the deployed runtime.

#### Scenario: Smoke test runs

- **WHEN** the deployed-runtime smoke test runs
- **THEN** it SHALL use the same configured eval image prefix as agent evals
- **AND** require the expected diagnosis structure from the deployed runtime

### Requirement: Garak Security Gate

Deployment SHALL optionally run garak security probing through the runtime handler path.

#### Scenario: Garak scan is enabled

- **WHEN** `GARAK_SCAN_ENABLED` is true
- **THEN** the workflow SHALL start the local garak REST adapter around the handler
- **AND** run the configured probe list
- **AND** enforce `GARAK_HIT_THRESHOLD`
- **AND** upload security reports as workflow artifacts

#### Scenario: Garak scan is disabled

- **WHEN** `GARAK_SCAN_ENABLED` is false
- **THEN** deployment SHALL skip garak probing
- **AND** still run the other configured quality gates

### Requirement: Quality Reporting

The deployment SHALL preserve evaluation and security results.

#### Scenario: Reports are produced

- **WHEN** evals or garak scans run
- **THEN** detailed reports SHALL be uploaded as GitHub Actions artifacts
- **AND** aggregate metrics SHALL be published to Langfuse when credentials are configured

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

### Requirement: Refactor Quality Gates
The repository SHALL enforce quality gates that cover the refactored architecture.

#### Scenario: CI runs after the refactor
- **WHEN** CI executes static checks and tests
- **THEN** it SHALL include the refactored source layout
- **AND** it SHALL run architecture boundary, compatibility import, and representative invocation tests

#### Scenario: Runtime evaluation gates run after the refactor
- **WHEN** agent evaluations, deployed smoke tests, or optional security probes run
- **THEN** they SHALL use the same public handler path as before the refactor
- **AND** they SHALL validate behavior through the refactored composition path
