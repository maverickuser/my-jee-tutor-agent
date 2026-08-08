## 1. Preserve Existing Agent Behavior

- [x] 1.1 Add characterization tests that lock current prompts, CrewAI tool definitions, mandatory first vision-tool action, call budgets, batching, retry settings, guardrail wiring, structured schemas, and public payload/response contracts.
- [x] 1.2 Add an architecture test requiring execution-profile and model-selection dependencies to remain outside domain, application policy, and tool behavior.

## 2. Add Infrastructure Execution Profiles

- [x] 2.1 Add immutable `ExecutionProfile` and `ModelBundle` infrastructure contracts with the specified CD and live generation/embedding defaults.
- [x] 2.2 Implement CD header canonicalization and HMAC-SHA256 verification with constant-time comparison, exact payload hashing, five-minute expiry, and safe errors.
- [x] 2.3 Update the AgentCore entrypoint and composition path to resolve the profile before client construction without adding profile or model fields to public tutor payloads.
- [x] 2.4 Add concurrency tests proving simultaneous CD and live composition cannot exchange models or mutate process environment configuration.

## 3. Configure CD Authentication Infrastructure

- [x] 3.1 Provision or reference the CD HMAC secret in AWS Secrets Manager and grant read access only to the CD and AgentCore runtime roles.
- [x] 3.2 Configure the AgentCore custom-header allowlist for the profile, timestamp, GitHub run ID, and signature headers.
- [x] 3.3 Update deployed diagnosis and profile smoke clients to hash the exact serialized payload and attach signed headers before Botocore SigV4 signing.
- [x] 3.4 Add security tests for missing, partial, malformed, expired, invalid, and payload-mismatched CD signatures and verify rejection occurs before any provider call.

## 4. Apply the Model Matrix

- [x] 4.1 Route diagnosis vision, CrewAI finalization, and profile synthesis through the request-scoped generation model without changing their prompts or orchestration.
- [x] 4.2 Route profile embeddings through the request-scoped embedding model without changing embedding input, dimensions, keys, or clustering logic.
- [x] 4.3 Configure CD defaults as `gemini/gemini-2.5-flash-lite` and `gemini/gemini-embedding-001` and live defaults as `gemini/gemini-3.6-flash` and `gemini/gemini-embedding-2`.
- [x] 4.4 Remove implicit GPT-4o selection based on `OPENAI_API_KEY` and prevent CD provider failures from falling back to live models.
- [x] 4.5 Omit `temperature`, `top_p`, and `top_k` only for Gemini 3.6 transport requests while retaining existing supported settings for other models.
- [x] 4.6 Add the dated Gemini 2.5 Flash-Lite retirement warning without automatically changing the configured model.

## 5. Complete Best-Effort Langfuse Coverage

- [x] 5.1 Preserve existing vision and profile-synthesis generation observations and add the resolved profile to safe metadata.
- [x] 5.2 Add one child generation observation for every CrewAI provider attempt, including distinct retry attempts.
- [x] 5.3 Add one child embedding observation for every LiteLLM embedding batch attempt, including distinct retry attempts.
- [x] 5.4 Record safe model, provider, operation, attempt, duration, status, token, cost, finish, and request-ID metadata when available.
- [x] 5.5 Catch Langfuse initialization, update, and flush failures; preserve provider behavior and emit structured redacted local warnings without queue or replay.

## 6. Verify and Document

- [x] 6.1 Add unit and integration tests for exact CD/live model resolution across diagnosis, CrewAI, profile synthesis, and embeddings.
- [x] 6.2 Add deployment tests for workflow defaults, header signing, header allowlisting, secret permissions, lifecycle warning, no GPT-4o inference, and no CD-to-live fallback.
- [x] 6.3 Add observability tests proving exactly one child observation per provider attempt when Langfuse is available and non-disruptive local warning behavior when it is unavailable.
- [x] 6.4 Run Ruff, the full test suite, coverage above 95%, architecture tests, deployment tests, and OpenSpec validation.
- [x] 6.5 Review the implementation diff and confirm no prompt, tool, orchestration, retry, guardrail, schema, profile-analysis, artifact, idempotency, or public-contract change was introduced.
