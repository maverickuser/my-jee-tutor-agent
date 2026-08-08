## ADDED Requirements

### Requirement: Execution profile resolution
The runtime SHALL resolve exactly one immutable execution profile at the infrastructure boundary before constructing model clients, and application, domain, agent, and tool logic SHALL NOT branch on that profile.

#### Scenario: Normal AgentCore invocation
- **WHEN** a request contains no CD execution-profile headers
- **THEN** the infrastructure composition SHALL resolve the `live` profile
- **AND** the existing task routing and agent behavior SHALL continue unchanged

#### Scenario: Authenticated CD invocation
- **WHEN** a request contains a valid signed CD execution profile
- **THEN** the infrastructure composition SHALL resolve the `cd` profile
- **AND** the existing task routing and agent behavior SHALL continue unchanged

#### Scenario: Concurrent CD and live invocations
- **WHEN** CD and live requests execute concurrently in one runtime process
- **THEN** each request SHALL retain its own immutable model configuration
- **AND** the system SHALL NOT mutate process environment variables to switch models

### Requirement: CD execution profile authentication
The runtime SHALL accept the CD execution profile only when allowlisted request headers contain a valid HMAC-SHA256 signature bound to the profile, timestamp, GitHub run identifier, and exact serialized payload hash.

#### Scenario: Valid CD signature
- **WHEN** the CD signature is valid and its timestamp is within five minutes of runtime UTC time
- **THEN** the runtime SHALL authorize the `cd` profile

#### Scenario: Payload is modified after signing
- **WHEN** the request payload hash does not match the payload bound into the CD signature
- **THEN** the runtime SHALL reject the request before constructing or calling a model client

#### Scenario: CD headers are invalid
- **WHEN** CD headers are partial, malformed, expired, or have an invalid signature
- **THEN** the runtime SHALL reject the request before constructing or calling a model client
- **AND** SHALL NOT reinterpret the request as `live`

#### Scenario: Caller supplies a model name
- **WHEN** a caller attempts to supply a generation or embedding model in the tutor payload
- **THEN** the existing strict payload contract SHALL reject the unknown field

### Requirement: Profile-specific model matrix
The infrastructure composition SHALL select generation and embedding models solely from the authenticated execution profile and configured profile defaults.

#### Scenario: CD model resolution
- **WHEN** the resolved execution profile is `cd`
- **THEN** vision diagnosis, CrewAI finalization, and profile synthesis SHALL use `gemini/gemini-2.5-flash-lite`
- **AND** profile embeddings SHALL use `gemini/gemini-embedding-001`

#### Scenario: Live model resolution
- **WHEN** the resolved execution profile is `live`
- **THEN** vision diagnosis, CrewAI finalization, and profile synthesis SHALL use `gemini/gemini-3.6-flash`
- **AND** profile embeddings SHALL use `gemini/gemini-embedding-2`

#### Scenario: CD model fails
- **WHEN** a configured CD model is unavailable or returns an error
- **THEN** the system SHALL preserve the existing bounded provider failure behavior
- **AND** SHALL NOT fall back to a live model

### Requirement: Core agent behavior preservation
Changing the execution profile SHALL change only provider model resolution and associated transport compatibility and telemetry, not the tutor's core logic.

#### Scenario: Agent is constructed for either profile
- **WHEN** infrastructure composition constructs the existing diagnosis or profile flow with either model bundle
- **THEN** prompts, tools, mandatory vision-tool use, call budgets, batching, retries, rate limits, guardrails, schemas, validation, conceptual-strand rules, reports, artifacts, idempotency, and public contracts SHALL remain unchanged

### Requirement: Gemini 3.6 transport compatibility
The model transport adapter SHALL omit sampling parameters deprecated by Gemini 3.6 without changing higher-level agent behavior.

#### Scenario: Live Gemini 3.6 call is constructed
- **WHEN** the resolved generation model is `gemini/gemini-3.6-flash`
- **THEN** the provider request SHALL omit `temperature`, `top_p`, and `top_k`
- **AND** prompts, response schemas, retry policy, and tool orchestration SHALL remain unchanged

#### Scenario: Gemini 2.5 Flash-Lite profile synthesis is constructed
- **WHEN** CD profile synthesis uses `gemini/gemini-2.5-flash-lite`
- **THEN** it SHALL retain temperature zero where supported by the existing classifier configuration
