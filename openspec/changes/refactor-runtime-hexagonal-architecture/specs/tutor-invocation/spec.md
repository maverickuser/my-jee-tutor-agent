## ADDED Requirements

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
