## MODIFIED Requirements

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

## ADDED Requirements

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
