## Why

The runtime has grown clear user-facing capabilities, but implementation responsibilities are concentrated across broad packages such as `jee_tutor.agent` and the invocation service. This makes CrewAI, LiteLLM, AWS, guardrail, artifact, email, and observability concerns harder to change independently and increases the risk that future feature work changes behavior accidentally.

## What Changes

- Introduce an internal hexagonal architecture boundary for the tutor runtime: stable API/domain/application modules, explicit ports, and concrete infrastructure adapters.
- Extract CrewAI, LiteLLM, AWS, email, artifact, status-store, guardrail, and observability integrations behind narrow interfaces.
- Split high-responsibility runtime modules into smaller application services and adapter modules while preserving existing invocation behavior.
- Keep public handler, payload, response, status, artifact, email, guardrail, diagnosis, and deployment contracts compatible with the existing specs.
- Add architecture-focused tests that prove the new boundaries preserve behavior and keep adapter details out of domain/application code.
- No **BREAKING** changes are intended.

## Capabilities

### New Capabilities
- `runtime-hexagonal-architecture`: Defines the internal architecture requirements for domain/application/ports/adapters boundaries, composition, compatibility, and architectural regression tests.

### Modified Capabilities
- `tutor-invocation`: Clarify that existing invocation behavior must be preserved while orchestration is moved behind application and port boundaries.
- `vision-diagnosis`: Clarify that CrewAI and LiteLLM remain implementation adapters for vision diagnosis, not domain/application dependencies.
- `runtime-safety-observability`: Clarify that guardrails, status recording, and observability are accessed through ports and remain privacy-preserving.
- `analysis-artifacts`: Clarify that artifact persistence is accessed through a port while preserving existing artifact behavior.
- `email-delivery`: Clarify that email delivery coordination and worker adapters remain behaviorally compatible behind ports.
- `deployment-quality-gates`: Clarify that CI/evaluation gates must cover the refactored module layout and compatibility import paths.

## Impact

- Affected code: `src/jee_tutor/agent`, `src/jee_tutor/invocation`, `src/jee_tutor/artifacts`, `src/jee_tutor/email`, `src/jee_tutor/curriculum`, `src/jee_tutor/handler.py`, `src/jee_tutor/app.py`, and relevant scripts.
- Affected tests: unit tests will move or expand around ports, adapters, application services, and compatibility wrappers.
- External APIs: no payload, response, status-record, artifact, email, deployment, or handler contract changes are expected.
- Dependencies: no new runtime dependency is required for the architectural split.
