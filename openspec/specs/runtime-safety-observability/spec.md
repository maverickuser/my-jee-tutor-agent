# Runtime Safety and Observability Specification

## Purpose

Defines runtime guardrails, privacy controls, and observability behavior around tutor invocations.
## Requirements
### Requirement: Runtime Guardrail Configuration

The system SHALL resolve Bedrock runtime guardrail settings from configuration and environment variables.

#### Scenario: Guardrail disabled

- **WHEN** guardrails are disabled or no guardrail identifier is configured
- **THEN** input and output checks SHALL allow the request without calling Bedrock Guardrails

#### Scenario: Guardrail enabled

- **WHEN** guardrails are enabled with an identifier
- **THEN** the system SHALL call `ApplyGuardrail` with the configured identifier, version, source, content, and output scope

#### Scenario: Environment overrides

- **WHEN** guardrail environment variables are set
- **THEN** they SHALL override the corresponding config file values

### Requirement: Input Guardrail Content

The system SHALL adapt invocation inputs into Bedrock Guardrail content.

#### Scenario: Text context is present

- **WHEN** the invocation includes task text
- **THEN** the input guardrail content SHALL include the stripped text

#### Scenario: Supported image payload is present

- **WHEN** image inclusion is enabled
- **AND** an image data URI is base64-encoded PNG, JPG, or JPEG
- **THEN** the input guardrail content SHALL include the decoded image bytes with Bedrock-compatible image format

#### Scenario: Unsupported guardrail image format

- **WHEN** an image is not a guardrail-supported PNG or JPEG data URI
- **THEN** the image SHALL be omitted from guardrail image content
- **AND** the invocation MAY still proceed to model analysis if the image input resolver supports the format

### Requirement: Guardrail Decisions

The system SHALL enforce guardrail decisions at the runtime boundary.

#### Scenario: Input guardrail intervenes

- **WHEN** the input guardrail returns an intervention
- **THEN** the invocation SHALL return an error response
- **AND** the tutor workflow SHALL NOT run
- **AND** the invocation status SHALL be recorded as `BLOCKED`

#### Scenario: Output guardrail intervenes

- **WHEN** the output guardrail returns an intervention
- **THEN** the system SHALL replace the model analysis with the guardrail output text when available
- **AND** otherwise return a generic blocked-response message

#### Scenario: Guardrail call fails closed

- **WHEN** a guardrail call raises an exception
- **AND** fail-closed mode is enabled
- **THEN** the guardrail check SHALL deny the request with a runtime guardrail failure message

#### Scenario: Guardrail call fails open

- **WHEN** a guardrail call raises an exception
- **AND** fail-closed mode is disabled
- **THEN** the guardrail check SHALL allow the request

### Requirement: Sensitive Information Reporting

The system SHALL report sensitive-information interventions without exposing matched values.

#### Scenario: PII is detected

- **WHEN** Bedrock Guardrails reports sensitive information policy matches
- **THEN** the system SHALL collect only the PII entity types or regex names whose action is not `NONE`
- **AND** SHALL NOT expose the matched sensitive values
- **AND** SHALL use the detected labels in the action reason when no explicit action reason is available

### Requirement: Langfuse Observability

The system SHALL make observability optional and privacy-preserving.

#### Scenario: Langfuse is unconfigured

- **WHEN** Langfuse credentials are absent
- **THEN** observability operations SHALL behave as no-ops

#### Scenario: Invocation span is created

- **WHEN** an invocation is processed
- **THEN** the system SHALL create an invocation span when observability is configured
- **AND** SHALL update the span with the final response

#### Scenario: Generation span is created

- **WHEN** the vision model is called
- **THEN** the system SHALL create a generation span when observability is configured
- **AND** SHALL include model, prompt metadata, attempt metadata, and token or cost accounting when available
- **AND** SHALL redact image-containing messages from the span input

### Requirement: LLM Transport Attempts

The system SHALL bound model transport retries.

#### Scenario: Gemini model call

- **WHEN** the configured vision model is Gemini
- **THEN** calls SHALL pass through the Gemini rate limiter
- **AND** only the configured retryable transport failures SHALL be retried

#### Scenario: Non-Gemini model call

- **WHEN** the configured vision model is not Gemini
- **THEN** the system SHALL issue a single LiteLLM completion attempt from the client retry layer

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
