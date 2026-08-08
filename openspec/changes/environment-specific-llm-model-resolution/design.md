## Context

The deployed runtime currently resolves operation-specific model settings from process configuration. CD smoke and evaluation paths can therefore execute the same expensive models as student-facing requests, and one eval path can select GPT-4o merely because an OpenAI credential exists. Vision and profile synthesis already create explicit Langfuse generation observations, while CrewAI finalization and embeddings do not have equivalent guaranteed coverage.

The tutor's controlled ReAct flow, mandatory vision tool, validation, retries, profile synthesis rules, and report generation are established behavior and are outside this change. The code-level contract is defined in `docs/llm-model-resolution-lld.md`.

## Goals / Non-Goals

**Goals:**

- Resolve CD generation to `gemini/gemini-2.5-flash-lite` and embeddings to `gemini/gemini-embedding-001`.
- Resolve live generation to `gemini/gemini-3.6-flash` and embeddings to `gemini/gemini-embedding-2`.
- Authenticate deployed CD selection without adding model fields to the public payload.
- Keep model selection immutable and isolated between concurrent requests.
- Trace every actual generation, embedding, and retry attempt in Langfuse when configured, with non-disruptive local logging fallback.
- Preserve all existing agent and tool behavior.

**Non-Goals:**

- Changing prompts, CrewAI orchestration, tool selection, batching, retries, guardrails, schemas, conceptual-strand rules, actionable insights, artifacts, idempotency, or API contracts.
- Adding a durable telemetry outbox, trace replay, or new profile caching.
- Automatically migrating away from Gemini 2.5 Flash-Lite in this change.
- Allowing callers to choose arbitrary models.

## Decisions

### Decision: Select models at the infrastructure composition boundary

The AgentCore adapter resolves an authenticated execution profile and supplies an immutable generation/embedding model bundle while constructing the existing clients. Application, domain, agent, and tool code remain unaware of the profile.

Rationale: this confines the change to configuration and adapters and prevents cost policy from changing tutoring behavior.

Alternatives considered:

- Branch inside agent or tool code: rejected because it couples core behavior to deployment context.
- Mutate environment variables per request: rejected because concurrent requests can leak configuration.
- Deploy two divergent agent implementations: rejected because it creates behavioral drift.

### Decision: Authenticate CD selection with signed custom headers

CD sends an execution profile, timestamp, run ID, and HMAC signature over the exact payload hash. AgentCore reads allowlisted headers from its request context and validates them before task routing. Missing headers mean live; malformed or invalid CD headers are rejected.

Rationale: task text, email domains, session IDs, and payload flags are caller-controlled and cannot establish a security boundary. Signed headers preserve the public payload and bind the CD assertion to one request.

Alternatives considered:

- Unsigned payload field: rejected because any caller could select the CD model.
- Infer from GitHub-shaped values: rejected because identifiers are forgeable.
- Separate agent logic for smoke tests: rejected because it would not exercise the deployed composition path.

### Decision: Use one generation model per execution profile

Vision diagnosis, CrewAI finalization, and profile synthesis receive the same generation model selected for the request. Embeddings use the selected embedding model.

Rationale: the requested matrix is simple, auditable, and prevents operation-specific defaults from silently defeating the cost policy.

Alternatives considered:

- Preserve different generation models per operation: rejected because it weakens the CD/live policy.
- Use a generation model for embeddings: rejected because embeddings require a dedicated embedding endpoint and vector contract.

### Decision: Adapt only provider request parameters required by Gemini 3.6

The Gemini 3.6 adapter omits deprecated sampling parameters. No prompt, schema, retry, or orchestration behavior changes.

Rationale: transport compatibility is necessary to adopt the selected model, while broader tuning would violate the behavior-preservation boundary.

### Decision: Make Langfuse best-effort and explicit at each provider boundary

Every provider attempt opens a child generation or embedding observation. Langfuse errors are caught and logged locally; there is no queue or replay and provider behavior is preserved.

Rationale: this closes visibility gaps without making student success depend on the telemetry service.

Alternatives considered:

- Rely solely on CrewAI/LiteLLM global telemetry: rejected because call coverage and parent association are not explicit.
- Fail the invocation when Langfuse fails: rejected because observability must remain optional.
- Add a durable outbox: rejected as unnecessary complexity for the requested failure policy.

## Risks / Trade-offs

- Gemini 2.5 Flash-Lite retires on October 16, 2026 -> keep the CD model configurable, emit a dated warning, and perform a later configuration-only migration.
- Signed-header configuration can drift between CD and AgentCore -> cover canonicalization, allowlisting, IAM, and secret resolution with deployment tests.
- Request-scoped configuration can accidentally fall back to globals -> make the model bundle immutable and test simultaneous CD/live construction.
- Gemini 3.6 output can differ from the former models -> retain all deterministic schemas and validation and run existing evals without changing their acceptance rules.
- Langfuse may lose traces during an outage -> emit structured local warnings and accept best-effort telemetry by design.

## Migration Plan

1. Add execution-profile and model-bundle types at the infrastructure boundary without changing current defaults.
2. Add signed CD header production and validation, custom-header allowlisting, and secret permissions.
3. Route client construction through the immutable model bundle and configure the requested matrix.
4. Remove credential-driven GPT-4o selection and CD-to-live fallback.
5. Add Gemini 3.6 transport compatibility for deprecated sampling parameters.
6. Complete explicit CrewAI and embedding Langfuse observations with local fallback logging.
7. Run behavior-preservation, concurrency, security, deployment, tracing, full-suite, Ruff, coverage, and OpenSpec validation.

Rollback restores the former model-variable wiring and stops sending CD headers. No data or public API migration is required.

## Open Questions

None. The model matrix, authentication boundary, observability failure policy, and core-logic non-goals are fixed by this change.
