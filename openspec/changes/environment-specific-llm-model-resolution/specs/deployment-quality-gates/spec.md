## ADDED Requirements

### Requirement: Environment-specific CD model gate
Deployment quality gates that make real provider calls SHALL use the authenticated CD execution profile and SHALL NOT select models based on the mere presence of provider credentials.

#### Scenario: CD generation runs
- **WHEN** deployed smoke, agent evaluation, or Garak execution makes a generation request
- **THEN** the request SHALL use `gemini/gemini-2.5-flash-lite`
- **AND** SHALL NOT use the live generation model

#### Scenario: CD profile embedding runs
- **WHEN** deployed profile smoke requires uncached embeddings
- **THEN** the request SHALL use `gemini/gemini-embedding-001`
- **AND** SHALL NOT use the live embedding model

#### Scenario: OpenAI credentials are configured
- **WHEN** `OPENAI_API_KEY` is present during CD
- **THEN** its presence SHALL NOT implicitly select GPT-4o or another OpenAI model

#### Scenario: CD model is unavailable
- **WHEN** a CD provider call cannot use its configured CD model
- **THEN** the affected optional quality gate SHALL fail with the original safe error
- **AND** SHALL NOT retry with a live model

### Requirement: Authenticated deployed CD invocation
The deployed-runtime smoke path SHALL sign its execution profile and payload, and runtime infrastructure SHALL allow and verify the required custom headers.

#### Scenario: CD invokes the deployed runtime
- **WHEN** a CD smoke script calls `InvokeAgentRuntime`
- **THEN** it SHALL add the signed CD profile, timestamp, GitHub run ID, and signature headers before SigV4 request signing
- **AND** the runtime SHALL receive those headers through its configured allowlist

#### Scenario: CD authentication secret is used
- **WHEN** CD signing or runtime verification resolves the HMAC secret
- **THEN** only the CD role and AgentCore runtime role SHALL have permission to read the secret
- **AND** workflow output, application logs, and Langfuse metadata SHALL NOT expose the secret or signature

### Requirement: CD model lifecycle warning
Deployment configuration SHALL identify the announced retirement of the configured Gemini 2.5 Flash-Lite CD generation model without changing agent logic automatically.

#### Scenario: Retirement warning period begins
- **WHEN** CD runs on or after September 16, 2026 while `gemini/gemini-2.5-flash-lite` remains configured
- **THEN** the workflow SHALL emit a clear warning that the model is scheduled to shut down on October 16, 2026
