## Context

The tutor runtime currently exposes stable behavior through the handler, invocation service, CrewAI workflow, vision diagnosis tool, guardrails, artifacts, status recording, email delivery, and deployment quality gates. Recent changes added deterministic guardrails, curriculum validation, CrewAI callbacks, status events, and richer artifact/evaluation behavior. Those capabilities work, but several modules now combine application orchestration with concrete runtime integrations.

The main pressure points are:

- `jee_tutor.agent` mixes CrewAI orchestration, LiteLLM transport, output validation, task guardrails, callbacks, prompts, model config, rate limiting, and observability.
- `jee_tutor.invocation.service` coordinates payload validation, idempotency, status recording, image resolution, guardrails, workflow execution, artifacts, email, and observability.
- `VisionAnalysisTool` owns CrewAI adapter behavior, duplicate-call coordination, batching, LiteLLM calls, status-store recording, and semantic retry state.
- Guardrail and curriculum validation code is valuable domain/application logic but is close to adapter and telemetry concerns.

The refactor should improve boundaries without changing the external runtime contract.

## Goals / Non-Goals

**Goals:**

- Introduce clear internal layers: API/contracts, domain, application, ports, adapters, and infrastructure composition.
- Preserve existing public behavior for payload validation, invocation status, vision diagnosis, guardrails, artifacts, email delivery, observability, evaluation, and handler entrypoints.
- Make application services testable with fake ports instead of concrete AWS, LiteLLM, CrewAI, Langfuse, or SES clients.
- Move vendor-specific request construction and error translation into adapter modules.
- Keep compatibility wrappers for existing imports during the migration.
- Add architecture and compatibility tests that protect the new boundaries.

**Non-Goals:**

- Changing invocation payloads, response shapes, status record schema, artifact URI behavior, or email delivery semantics.
- Replacing CrewAI, LiteLLM, Bedrock Guardrails, DynamoDB, S3, SES, Langfuse, or AgentCore.
- Introducing a new dependency-injection framework.
- Rewriting all modules in one step when thin wrappers can preserve behavior.
- Removing legacy compatibility imports in this change.

## Decisions

### Decision: Use lightweight ports instead of a dependency-injection framework

Define narrow `Protocol` or abstract interfaces for external effects, then inject implementations through constructors or a composition function.

Rationale: the codebase is small enough that a framework would add more surface area than value. Python protocols keep adapters easy to fake in tests and avoid runtime coupling.

Alternatives considered:

- Full dependency-injection container: rejected because it adds indirection and configuration complexity.
- Continue passing concrete classes: rejected because it keeps application code coupled to adapter details.

### Decision: Keep the handler and compatibility modules stable

The public handler path and supported legacy imports should remain stable while delegating to the new composition/application modules.

Rationale: deployment, CI, evaluations, smoke tests, and compatibility tests already depend on these entrypoints. A boundary refactor should not become a runtime contract migration.

Alternatives considered:

- Rename public entrypoints immediately: rejected because it creates avoidable deployment and user impact.
- Duplicate old and new implementations: rejected because it increases divergence risk.

### Decision: Extract application services before moving adapters deeply

Start by introducing application-level services and ports around current behavior, then move concrete implementations under adapter packages.

Rationale: this keeps behavior tests meaningful throughout the refactor and allows small commits with rollback points.

Alternatives considered:

- Move files first and repair imports later: rejected because it makes regressions harder to isolate.
- Leave packages in place and only add protocols: rejected because it would not solve the current responsibility concentration.

### Decision: Treat CrewAI and LiteLLM as adapters

The diagnosis use case should own batching, expected question number handling, semantic retry policy, and validation coordination. CrewAI tool classes and LiteLLM message construction should be concrete adapters.

Rationale: the domain behavior is tutoring diagnosis, not a CrewAI tool lifecycle or LiteLLM payload format. This makes future runtime or model-provider changes lower-risk.

Alternatives considered:

- Keep all vision behavior in `VisionAnalysisTool`: rejected because it is already a high-responsibility class.
- Make CrewAI the application boundary: rejected because it would keep domain logic coupled to one orchestrator.

### Decision: Separate policy from side effects in guardrails and validation

Output extraction, deterministic validation, taxonomy validation, and retry decisions should be pure or mostly pure services. Telemetry, status events, and CrewAI callback wiring should call those services rather than own policy.

Rationale: retry and validation logic must be deterministic, easy to test, and independent from runtime observability.

Alternatives considered:

- Keep policy inside callbacks/tools: rejected because it hides decisions behind adapter lifecycle hooks.
- Move validation entirely into domain with all telemetry: rejected because telemetry is an external effect and belongs behind ports.

## Risks / Trade-offs

- Broad import movement can break tests or deployed entrypoints -> preserve compatibility wrappers and run compatibility import tests throughout the migration.
- Too many tiny packages can make the repo harder to navigate -> keep boundaries purposeful and avoid splitting modules that do not cross external-effect or domain/application lines.
- Ports can become vague pass-through abstractions -> define ports around use-case needs, not vendor APIs.
- Refactoring while behavior is changing can hide regressions -> keep this change behavior-preserving and defer new features.
- Adapter extraction can temporarily duplicate code -> prefer move-and-wrap steps with tests before deleting old paths.

## Migration Plan

1. Add new package skeletons for `api`, `domain`, `application`, `ports`, `adapters`, and `infrastructure` with no behavior change.
2. Move stable request/response/status contracts and pure diagnosis/curriculum models behind compatibility imports.
3. Introduce ports for image resolution, workflow execution, guardrails, observability, status recording, artifacts, email, LLM, and taxonomy loading.
4. Extract invocation orchestration into an application service wired by a composition root.
5. Split vision diagnosis into application/domain services plus CrewAI and LiteLLM adapters.
6. Split guardrail, output validation, taxonomy validation, and retry policy from telemetry and callback side effects.
7. Move concrete AWS, Langfuse, CrewAI, LiteLLM, SES, and artifact implementations into adapter packages.
8. Keep old import paths as thin wrappers and verify them with compatibility tests.
9. Run unit tests, Ruff, coverage, OpenSpec validation, evals, and smoke/security gates where applicable.

Rollback strategy: each phase should keep public handlers and compatibility modules delegating to one implementation. If a phase regresses behavior, revert that phase while keeping earlier boundary-safe phases.

## Open Questions

- Should compatibility wrappers be marked with a deprecation timeline in this change, or should removal be planned as a later OpenSpec change?
- Should architecture boundary tests use a small custom import scanner, or should the repo add a dedicated architecture-test dependency later?
- Should `curriculum` remain a top-level bounded context or move under `domain` with only loaders/adapters outside it?
