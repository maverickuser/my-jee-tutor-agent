## MODIFIED Requirements

### Requirement: Langfuse Observability
The system SHALL make observability optional, privacy-preserving, execution-profile aware, and explicit for every external model attempt.

#### Scenario: Langfuse is unconfigured
- **WHEN** Langfuse credentials are absent
- **THEN** observability operations SHALL behave as no-ops
- **AND** provider calls and existing application behavior SHALL continue

#### Scenario: Invocation span is created
- **WHEN** an invocation is processed
- **THEN** the system SHALL create one parent invocation span when observability is configured
- **AND** SHALL include the resolved execution profile and safe model metadata
- **AND** SHALL update the span with the final response

#### Scenario: Generation attempt is made
- **WHEN** the system makes a vision diagnosis, CrewAI finalization, or profile-synthesis provider attempt
- **THEN** the system SHALL create exactly one child generation observation when observability is configured
- **AND** SHALL include execution profile, model, provider, operation, attempt, status, duration, and token or cost accounting when available
- **AND** each provider retry SHALL create a distinct attempt observation

#### Scenario: Embedding attempt is made
- **WHEN** the profile service makes an embedding provider attempt
- **THEN** the system SHALL create exactly one child embedding observation when observability is configured
- **AND** SHALL include execution profile, model, provider, batch size, attempt, status, duration, and token or cost accounting when available

#### Scenario: Trace input is recorded
- **WHEN** invocation, generation, or embedding metadata is sent to Langfuse or local fallback logging
- **THEN** the system SHALL omit raw image data, base64 payloads, recipient email, credentials, CD signatures, full prompts, and full model responses

#### Scenario: Langfuse operation fails
- **WHEN** Langfuse initialization, observation update, or flush raises an exception
- **THEN** the system SHALL preserve the provider result or original provider error
- **AND** SHALL emit a structured local warning with safe invocation, operation, model, attempt, usage, call status, and Langfuse error metadata when available
- **AND** SHALL NOT queue or replay the failed trace
