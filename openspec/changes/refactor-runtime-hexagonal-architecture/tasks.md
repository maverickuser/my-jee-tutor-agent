## 1. Architecture Skeleton

- [x] 1.1 Add package skeletons for API/contracts, domain, application, ports, adapters, and infrastructure composition.
- [x] 1.2 Add lightweight architecture documentation in module docstrings or package README files explaining allowed dependency direction.
- [x] 1.3 Add architecture boundary tests that fail if domain modules import concrete CrewAI, LiteLLM, boto3, Langfuse, AgentCore, or SES adapter modules.

## 2. Contracts and Domain Extraction

- [x] 2.1 Move stable invocation request, response, status, and LLM-call models behind an API/contracts package while preserving existing import paths.
- [x] 2.2 Move pure diagnosis output models, Markdown rendering/validation helpers, and deterministic validation policies behind domain/application modules while preserving existing behavior.
- [x] 2.3 Move curriculum taxonomy models and deterministic validation helpers behind domain/application boundaries while keeping loader implementations outside domain code.
- [x] 2.4 Add compatibility import tests for existing public and legacy module paths.

## 3. Ports and Composition

- [x] 3.1 Define ports for image resolution, tutor workflow execution, LLM vision completion, guardrail checks, observability, status recording, artifact writing, email delivery, idempotency, and taxonomy loading.
- [x] 3.2 Add a composition root that wires configured concrete implementations for handler and local runtime usage.
- [x] 3.3 Refactor handler/app startup to use the composition root without changing public handler behavior.
- [x] 3.4 Add tests proving application services can run with fake or in-memory port implementations.

## 4. Invocation Application Refactor

- [x] 4.1 Extract invocation orchestration from `jee_tutor.invocation.service` into an application service that depends on ports.
- [x] 4.2 Keep existing `TutorInvocationService` import path as a thin compatibility wrapper or alias.
- [x] 4.3 Verify payload validation, idempotency, image input resolution, status recording, guardrail blocking, response shape, artifact metadata, and email metadata remain compatible.

## 5. Vision Diagnosis Refactor

- [x] 5.1 Extract vision diagnosis batching, expected-question-number handling, semantic retry policy, and diagnosis validation into application/domain services.
- [x] 5.2 Convert the CrewAI vision tool into an adapter that delegates to the vision diagnosis application interface.
- [x] 5.3 Convert LiteLLM multimodal request construction and response parsing into a concrete LLM adapter.
- [x] 5.4 Preserve duplicate-call caching, failure replay, semantic retry, batch merge, and redacted observability behavior with focused tests.

## 6. Safety, Observability, Artifacts, and Email Adapters

- [x] 6.1 Move Bedrock guardrail request/response handling behind a guardrail adapter while application code uses a guardrail port.
- [x] 6.2 Move Langfuse and DynamoDB status/event implementations behind observability and status ports while preserving redaction and append-only event behavior.
- [x] 6.3 Move PDF/Markdown/S3 artifact persistence behind an artifact-writer adapter while preserving artifact URI and fallback behavior.
- [x] 6.4 Move Lambda/SES email coordination and worker implementation details behind email adapters while preserving delivery idempotency and outcomes.

## 7. Scripts and Runtime Adapters

- [x] 7.1 Keep scripts as thin CLI wrappers around package services for taxonomy generation, evals, smoke tests, and security probes.
- [x] 7.2 Update imports in tests, eval scripts, and deployment helpers to use stable public or application/composition entrypoints.
- [x] 7.3 Remove generated cache artifacts from source/test trees if present and confirm ignore rules prevent reintroducing them.

## 8. Verification

- [x] 8.1 Run OpenSpec validation for `refactor-runtime-hexagonal-architecture`.
- [x] 8.2 Run Ruff over source, tests, and scripts.
- [x] 8.3 Run the full unit test suite with coverage and confirm the configured threshold still passes.
- [x] 8.4 Run representative evaluation, smoke, or security gates where local credentials/configuration allow.
