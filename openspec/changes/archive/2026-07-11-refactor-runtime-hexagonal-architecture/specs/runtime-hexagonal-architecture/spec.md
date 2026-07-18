## ADDED Requirements

### Requirement: Layered Runtime Boundaries
The system SHALL organize tutor runtime code into explicit API, domain, application, port, adapter, and infrastructure boundaries.

#### Scenario: Domain code is independent of runtime adapters
- **WHEN** domain modules are imported
- **THEN** they SHALL NOT import CrewAI, LiteLLM, boto3, Langfuse, AgentCore, or SES adapter modules
- **AND** they SHALL expose deterministic data models, validation helpers, and domain policies only

#### Scenario: Application code depends on ports
- **WHEN** application services coordinate a tutor invocation or diagnosis workflow
- **THEN** they SHALL depend on explicit port interfaces for external effects
- **AND** they SHALL NOT instantiate concrete AWS, LiteLLM, CrewAI, Langfuse, or email clients directly

#### Scenario: Adapters implement ports
- **WHEN** infrastructure integrations are needed
- **THEN** concrete adapters SHALL implement the corresponding port interface
- **AND** adapter modules SHALL contain vendor-specific request construction, response parsing, and error translation

### Requirement: Composition Root
The system SHALL assemble concrete runtime dependencies in a dedicated composition path.

#### Scenario: Runtime handler starts
- **WHEN** the AgentCore or local handler creates a tutor invocation service
- **THEN** concrete adapters SHALL be wired from configuration in one composition path
- **AND** the handler SHALL invoke application services through stable application interfaces

#### Scenario: Tests instantiate application services
- **WHEN** unit tests exercise application behavior
- **THEN** they SHALL be able to provide fake or in-memory port implementations without importing vendor adapters

### Requirement: Compatibility During Refactor
The system SHALL preserve existing public import and handler contracts during the architectural migration.

#### Scenario: Existing entrypoints are imported
- **WHEN** existing supported entrypoints such as `jee_tutor.handler`, `jee_tutor.app`, and documented compatibility modules are imported
- **THEN** imports SHALL continue to succeed
- **AND** they SHALL delegate to the refactored application or composition modules

#### Scenario: External behavior is compared
- **WHEN** the refactored runtime handles valid, invalid, blocked, artifact-producing, and email-requesting invocations
- **THEN** responses and status side effects SHALL remain compatible with the existing specifications

### Requirement: Architecture Regression Tests
The system SHALL include tests that protect the new architecture boundaries.

#### Scenario: Boundary tests run
- **WHEN** the unit test suite runs
- **THEN** it SHALL verify that domain and application modules do not depend on concrete adapter packages
- **AND** it SHALL verify that adapter implementations satisfy the expected port contracts

#### Scenario: Compatibility tests run
- **WHEN** the unit test suite runs
- **THEN** it SHALL verify that legacy import paths and runtime entrypoints still resolve
- **AND** it SHALL verify representative invocation flows through the refactored composition path
