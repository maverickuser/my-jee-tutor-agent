## ADDED Requirements

### Requirement: Safety and Observability Port Boundary
The system SHALL access guardrails, invocation status recording, LLM-call recording, and observability through explicit ports.

#### Scenario: Guardrails are evaluated
- **WHEN** input or output guardrail checks run
- **THEN** application services SHALL use a guardrail port
- **AND** Bedrock-specific request and response handling SHALL remain inside the Bedrock guardrail adapter

#### Scenario: Runtime telemetry is recorded
- **WHEN** invocation, task, generation, or retry telemetry is emitted
- **THEN** application services SHALL use observability and status ports
- **AND** concrete Langfuse and DynamoDB implementations SHALL preserve the existing privacy and redaction requirements
