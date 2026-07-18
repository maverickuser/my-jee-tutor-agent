## Why

The current tutor workflow has structured output validation, but CrewAI task-output correctness is still enforced outside the CrewAI task boundary. The new docs define a controlled ReAct design where CrewAI can orchestrate the vision tool and perform one bounded recovery while deterministic guardrails prevent invalid output from reaching rendering, artifacts, email, or successful responses.

## What Changes

- Add deterministic CrewAI task guardrails for diagnosis-task output correctness.
- Constrain ReAct orchestration to approved vision-tool use, cached finalization retry, and one semantic vision retry.
- Add invocation-scoped tool observation state for valid, rejected, replayed, and replaced observations.
- Add CrewAI lifecycle hooks for safe observability at kickoff and task boundaries.
- Add deterministic curriculum chapter/topic validation backed by an approved taxonomy artifact loaded from S3 or local file.
- Add a manually approved taxonomy generation path for producing and publishing taxonomy JSON from syllabus PDFs.
- Extend invocation status tracking with CrewAI lifecycle, guardrail, retry, and richer nested LLM-call telemetry requirements.
- Extend deployment quality gates to cover controlled ReAct, task guardrail, taxonomy generation, and taxonomy validation evidence.

## Capabilities

### New Capabilities

- `controlled-crewai-orchestration`: Controlled ReAct behavior, vision-tool cache policy, finalization retry, semantic vision retry, and call budgets.
- `crewai-task-guardrail`: Deterministic task-output correctness validation attached to the CrewAI diagnosis task.
- `crewai-hooks`: CrewAI lifecycle hooks for safe observability and status telemetry.
- `curriculum-taxonomy-validation`: Approved taxonomy loading, deterministic chapter/topic validation, taxonomy retry behavior, and taxonomy generation/publishing controls.

### Modified Capabilities

- `tutor-invocation`: Invocation status must capture CrewAI guardrail/retry lifecycle and continue to prevent artifacts, email, and successful responses after guarded workflow failure.
- `vision-diagnosis`: Vision tool state and batching must support rejected observations, one semantic retry, cached replay, and guardrail-owned final-output validation.
- `deployment-quality-gates`: CI/CD gates must prove task guardrail execution, controlled ReAct behavior, taxonomy validation, and safe taxonomy publishing.

## Impact

Affected areas include `src/jee_tutor/agent` CrewAI factories, workflow, tools, output validation, observability, status-store writes, new curriculum modules, taxonomy generation scripts, tests, eval gates, and deployment configuration. External invocation payload shape remains backward-compatible, but successful responses and artifact/email creation become stricter because they require a guardrail-approved diagnosis task output.
