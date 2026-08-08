# Environment-Specific LLM Model Resolution LLD

Status: Implemented

OpenSpec change: `environment-specific-llm-model-resolution`

## Purpose

Select cost-oriented models for CI/CD and quality-oriented models for live
AgentCore requests without changing how the JEE tutor agent reasons, invokes
tools, validates diagnoses, synthesizes profiles, or produces artifacts.

The model matrix is the primary behavior introduced by this design:

| Execution profile | Generation model | Embedding model |
| --- | --- | --- |
| `cd` | `gemini/gemini-2.5-flash-lite` | `gemini/gemini-embedding-001` |
| `live` | `gemini/gemini-3.6-flash` | `gemini/gemini-embedding-2` |

## Non-Goals and Preserved Behavior

This change does not modify:

- system, task, tool, or profile prompts;
- the mandatory first vision-tool action;
- CrewAI agents, tasks, tools, call budgets, or task retries;
- vision image batching, semantic retry, or rate limiting;
- Bedrock input/output guardrails or curriculum validation;
- diagnosis or profile structured-output schemas;
- candidate retrieval, conceptual-strand validation, or actionable insights;
- PDF generation, S3 paths, email behavior, or invocation idempotency;
- public request payloads, task aliases, or response shapes.

Model selection and telemetry remain adapter and infrastructure concerns. The
domain and application layers do not branch on an execution profile.

## Current Provider Call Inventory

| Operation | Existing integration | Required profile-aware model | Trace requirement |
| --- | --- | --- | --- |
| Diagnosis vision | LiteLLM completion through `VisionLLMClient` | Generation model | One generation observation per transport attempt |
| CrewAI finalization | CrewAI LiteLLM adapter | Generation model | One generation observation per provider attempt |
| Profile semantic synthesis | LiteLLM completion | Generation model | One generation observation per provider attempt |
| Profile evidence embedding | LiteLLM embedding | Embedding model | One embedding observation per batch attempt |
| Bedrock Guardrails | AWS `ApplyGuardrail` | Unchanged | Existing safe runtime telemetry; not an LLM model selection |
| Local mandatory tool action | Local fixed response | No model | Optional non-generation orchestration span |

Mocked tests do not create provider-call observations. Cache and idempotency hits
do not create generation or embedding observations because no provider call
occurs.

## Architecture

```text
AgentCore request
  -> entrypoint adapter resolves and authenticates execution profile
  -> infrastructure composition selects immutable ModelBundle
  -> existing diagnosis/profile services receive configured clients
  -> existing agent and tools execute unchanged
  -> provider adapters emit best-effort Langfuse child observations
```

### Execution profile

The execution profile is an infrastructure value, not a public tutor payload
field:

```python
class ExecutionProfile(StrEnum):
    CD = "cd"
    LIVE = "live"
```

The entrypoint resolves it before task routing. The handler passes an immutable
model bundle into the composition root; it does not pass profile checks into
agent, application, tool, or domain logic.

```python
@dataclass(frozen=True)
class ModelBundle:
    generation_model: str
    embedding_model: str
```

The composition root applies `generation_model` to the existing vision,
CrewAI, and profile-classifier client configurations. It applies
`embedding_model` to the existing profile embedding client configuration.

Model names are never accepted from the tutor payload. Process environment
variables are never mutated while handling a request. This prevents concurrent
CD and live invocations in the same AgentCore process from exchanging models.

## CD Authentication

Normal requests have no CD headers and resolve to `live`. A deployed smoke or
evaluation request can select `cd` only with these allowlisted custom headers:

- `X-JEE-Execution-Profile: cd`
- `X-JEE-CD-Timestamp: <unix-seconds>`
- `X-JEE-CD-Run-ID: <github-run-id>`
- `X-JEE-CD-Signature: <hex-hmac>`

The CD script calculates `SHA-256` over the exact serialized request payload and
then signs this canonical UTF-8 value:

```text
v1\ncd\n<timestamp>\n<github-run-id>\n<payload-sha256>
```

Signature rules:

- use HMAC-SHA256 and lowercase hexadecimal encoding;
- compare signatures with a constant-time comparison;
- accept timestamps within five minutes of runtime UTC time;
- reject missing, partial, malformed, expired, or invalid CD headers before
  constructing any provider client;
- never treat an invalid CD request as live;
- never log the signature, secret, or canonical value.

The HMAC secret is held in AWS Secrets Manager. The AgentCore execution role and
CD GitHub role receive read access to that secret only. CD scripts register the
custom headers before Botocore signs `InvokeAgentRuntime`. Terraform configures
the AgentCore custom-header allowlist.

## Model Configuration

Configuration exposes these defaults:

```text
CD_GENERATION_MODEL=gemini/gemini-2.5-flash-lite
CD_EMBEDDING_MODEL=gemini/gemini-embedding-001
LIVE_GENERATION_MODEL=gemini/gemini-3.6-flash
LIVE_EMBEDDING_MODEL=gemini/gemini-embedding-2
```

Legacy operation-specific model variables may remain as explicit deployment
overrides, but implicit credential-based selection is removed. In particular,
the presence of `OPENAI_API_KEY` does not select GPT-4o.

No CD error path falls back to a live model. A missing or unavailable CD model
fails the optional CD job with the original provider/configuration error.

### Gemini 3.6 transport compatibility

The Gemini 3.6 request adapter omits `temperature`, `top_p`, and `top_k` because
those sampling parameters are deprecated for this model. It does not alter
prompts, schemas, retry policy, output validation, or tool orchestration to
compensate. Other models retain their existing supported settings, including
temperature zero for profile synthesis on Gemini 2.5 Flash-Lite.

### Gemini 2.5 Flash-Lite lifecycle

Gemini 2.5 Flash-Lite is scheduled to shut down on October 16, 2026. CD emits a
clear warning beginning September 16, 2026. Changing its successor is a later
configuration-only change and must not require changes to agent logic.

## Langfuse Observability

The existing invocation span remains the parent. Each actual provider attempt
creates exactly one child observation when Langfuse is configured:

| Observation | Type | Required metadata |
| --- | --- | --- |
| `diagnosis-vision` | generation | profile, model, provider, batch, attempt, status |
| `diagnosis-finalization` | generation | profile, model, provider, attempt, status |
| `profile-strand-synthesis` | generation | profile, model, provider, pair count, attempt, status |
| `profile-evidence-embedding` | embedding | profile, model, provider, batch size, attempt, status |

Include input, output, cached, reasoning, and total tokens plus reported or
estimated cost when the provider response exposes them. Include duration,
finish reason, safe error type, and provider request identifier when available.
Every provider retry receives a distinct attempt observation.

Tracing is best-effort. Langfuse initialization, observation update, or flush
failure is caught and written as a structured local warning. The warning
includes invocation ID, operation, model, attempt, call status, safe usage, and
Langfuse error type when known. It excludes prompts, raw responses, email,
image/base64 data, credentials, and signatures. There is no trace queue or
replay. A tracing failure never changes the provider result or replaces the
original provider error.

## Failure Behavior

| Condition | Required result |
| --- | --- |
| No CD headers | Resolve `live` |
| Valid CD headers | Resolve `cd` |
| Invalid/expired CD headers | Reject before provider call |
| CD model unavailable | Fail CD operation; no live fallback |
| Langfuse unavailable | Continue provider operation and log locally |
| Provider failure | Preserve existing retry/error behavior |

## Test Design

Unit tests cover profile resolution, HMAC canonicalization, constant-time
validation, expiry, payload tampering, model matrices, Gemini 3.6 request
parameters, and tracing failure isolation. Concurrency tests construct CD and
live services simultaneously and assert that each adapter retains its own model.

Deployment tests verify workflow defaults, custom-header allowlisting, secret
permissions, removal of implicit GPT-4o selection, and absence of CD-to-live
fallback. Behavior-preservation tests assert that prompts, tool definitions,
mandatory tool execution, call budgets, retries, guardrails, schemas, and public
contracts are unchanged.

The full repository suite, Ruff, OpenSpec validation, and coverage above 95%
must pass before implementation is complete.
