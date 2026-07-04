# Diagnosis Quality Pipeline Implementation Plan

Status: Implemented

## Purpose

Maintain a reliable diagnosis pipeline based on structured output, constrained
CrewAI ReAct orchestration, runtime guardrails, deterministic rendering, and
deployment validation.

Source specifications:

- [`structured-output-spec.md`](structured-output-spec.md)
- [`crewai-react-diagnosis-spec.md`](crewai-react-diagnosis-spec.md)

## Runtime Flow

```text
Invocation
  -> payload and image validation
  -> input guardrail
  -> constrained CrewAI diagnosis orchestration
  -> invocation-scoped memoized vision tool
  -> structured diagnosis validation
  -> deterministic Markdown rendering
  -> output guardrail
  -> optional artifact creation
  -> response
```

## Invariants

1. An invocation accepts exactly one image source.
2. One logical invocation executes the vision tool at most once.
3. Duplicate CrewAI tool requests replay the memoized observation.
4. Provider retry ownership remains in `VisionLLMClient`.
5. CrewAI final output must preserve the tool observation.
6. Structured diagnosis row count and question order match resolved images.
7. Markdown rendering occurs only after structured validation succeeds.
8. Runtime guardrails execute at the input and output boundaries.
9. Artifact writes occur only after successful diagnosis and output handling.
10. Idempotent replay does not rerun diagnosis or rewrite artifacts.

## Delivery Stages

### Structured diagnosis

- Keep the diagnosis response schema strict.
- Reject malformed JSON, missing fields, duplicate questions, and row-count
  mismatches.
- Render Markdown in application code.

### ReAct orchestration

- Keep the vision tool invocation-scoped and memoized.
- Disable hidden provider and CrewAI retry layers.
- Enforce orchestration call and iteration budgets.
- Reject final answers that differ from the memoized tool observation.

### Runtime safety

- Apply input and output guardrails.
- Redact images, prompts, credentials, and unbounded model output from logs.
- Return bounded operational error details.

### Artifacts and idempotency

- Write artifacts only after the workflow succeeds.
- Sanitize artifact names.
- Return a completed response for matching idempotency replays.
- Reject conflicting reuse of an idempotency key.

### CI/CD

- Run Ruff and the unit/integration test suite.
- Run mandatory ReAct diagnosis cases.
- Run deployed-runtime smoke coverage for row count, commit SHA, artifacts, and
  idempotent replay.
- Run agent evals and the configured garak security scan.

## Definition of Done

- Tests and lint pass.
- CD contains no hidden retry or duplicate vision execution path.
- Deployed smoke verifies the expected image-to-row mapping.
- Logs and reports contain no sensitive image or credential payloads.
- Operational documentation matches the runtime and CD workflow.
