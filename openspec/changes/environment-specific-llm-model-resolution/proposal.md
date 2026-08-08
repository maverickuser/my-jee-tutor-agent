## Why

CI/CD currently exercises the deployed tutor through the same model configuration used by student-facing AgentCore invocations, which makes quality gates more expensive than necessary and allows credentials to influence model selection implicitly. The runtime needs an explicit, authenticated execution profile that selects cost-oriented CD models or quality-oriented live models without changing the tutor agent's prompts, orchestration, tools, validation, or reports.

## What Changes

- Introduce request-scoped `cd` and `live` execution profiles resolved at the AgentCore infrastructure boundary.
- Resolve one generation model and one embedding model for each profile:
  - CD: `gemini/gemini-2.5-flash-lite` and `gemini/gemini-embedding-001`.
  - Live: `gemini/gemini-3.6-flash` and `gemini/gemini-embedding-2`.
- Authenticate deployed CD smoke requests with signed, allowlisted AgentCore request headers; requests without CD headers remain live, while invalid CD headers are rejected before any model call.
- Remove credential-driven GPT-4o selection and prohibit automatic fallback from a CD model to a live model.
- Make model configuration immutable and request-scoped so concurrent CD and live invocations cannot affect one another.
- Complete best-effort Langfuse observations for every generation, embedding, and retry attempt, with structured local warnings when Langfuse is unavailable.
- Add lifecycle warning coverage for the planned retirement of Gemini 2.5 Flash-Lite.
- Preserve the existing agent core logic. This change does not modify prompts, mandatory tool use, CrewAI orchestration, batching, retry policy, guardrails, schemas, conceptual-strand logic, report generation, artifacts, idempotency, or public request/response contracts.

## Capabilities

### New Capabilities

- `llm-execution-profile-routing`: Authenticated, request-scoped selection of CD and live generation and embedding models at the infrastructure composition boundary.

### Modified Capabilities

- `runtime-safety-observability`: Extend privacy-preserving Langfuse coverage to every external generation, embedding, and retry attempt without making observability a runtime dependency.
- `deployment-quality-gates`: Require CD evaluations, smoke tests, and security probes to use the configured CD models and prevent implicit use of live or GPT-4o models.

## Impact

- AgentCore entrypoint and infrastructure composition gain execution-profile resolution and request-scoped model bundles.
- CD smoke scripts and Terraform gain custom-header allowlisting, signature verification configuration, and least-privilege secret access.
- LiteLLM generation and embedding adapters gain consistent Langfuse observation coverage and local logging fallback.
- Model configuration and CD workflow defaults change; agent application behavior and public API contracts do not.
