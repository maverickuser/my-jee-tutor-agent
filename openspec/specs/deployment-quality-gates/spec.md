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
