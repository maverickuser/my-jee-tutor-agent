## Context

The runtime already has a thin AgentCore invocation layer, image normalization, a CrewAI diagnosis workflow, a memoized vision analyzer tool, structured diagnosis parsing, output rendering, Bedrock runtime guardrails, artifact writing, email delivery, Langfuse observability, and optional DynamoDB invocation status records.

The source docs define the next step: make CrewAI's ReAct loop responsible only for bounded orchestration and recovery, and move CrewAI task-output correctness into a deterministic `Task.guardrail`. Runtime safety guardrails remain separate and continue to apply at the invocation boundary.

## Goals / Non-Goals

**Goals:**

- Attach a deterministic diagnosis task guardrail to the CrewAI task.
- Keep ReAct bounded to the approved vision tool, cached finalization retry, and one semantic vision retry.
- Track valid, rejected, replayed, and replaced tool observations in invocation-scoped state.
- Add safe CrewAI lifecycle hooks for start, completion, and task telemetry.
- Validate diagnosis chapter/topic labels against an approved taxonomy artifact without using an LLM judge.
- Preserve privacy rules for image data, recipient email, full model output, and full invalid output.
- Ensure rendering, Bedrock output guardrails, artifacts, email, and success responses happen only after task guardrail approval.

**Non-Goals:**

- No new external invocation payload shape.
- No LLM-based task guardrail or LLM-based curriculum judge.
- No direct runtime validation against source PDFs.
- No use of hooks as the correctness gate.
- No artifact, email, S3, SES, or DynamoDB work inside the task guardrail.
- No initial `step_callback` enforcement until CrewAI `0.150.0` callback payload compatibility is verified.

## Decisions

### Deterministic Task Guardrail

Implement `src/jee_tutor/agent/task_guardrails.py` with a factory that receives invocation-scoped `VisionToolCallState`, expected image count, expected question numbers, and optional taxonomy validator. The returned callable extracts task output, confirms a successful tool observation exists, rejects non-JSON final output, validates the tool observation, canonicalizes JSON, compares final output to the observation, validates the diagnosis schema and invocation shape, and optionally validates chapter/topic labels.

Alternative considered: continue post-workflow validation after `crew.kickoff()`. That keeps behavior outside CrewAI and cannot use CrewAI's guardrail retry channel cleanly, so the task guardrail becomes the authoritative CrewAI/ReAct correctness gate.

### Two Retry Categories

Classify failures into cached finalization retry, semantic vision retry, and non-retryable failure.

- Cached finalization retry: the tool observation is valid, but the agent final output is malformed or differs from the observation. The tool may be called again but must replay the cached valid observation.
- Semantic vision retry: the observation itself is invalid for this invocation, including schema, count, question-number, or taxonomy failures. The tool marks the observation rejected and may execute the model one more time.
- Non-retryable: no observation, tool failure, wrong image source, image-count mismatch before observation validation, or exhausted semantic retry budget.

Alternative considered: one generic retry. That would obscure whether another model call is allowed and risks accidental extra vision executions.

### Invocation-Scoped Tool State

Extend `VisionToolCallState` rather than adding process-global coordination. The state must distinguish request count, real execution count, successful execution count, transport attempts, observation validation, rejection category, semantic retry count, and semantic retry budget.

This keeps retry policy local to one invocation and maintains the existing memoization pattern.

### Hooks as Telemetry Only

Add `src/jee_tutor/agent/crew_callbacks.py` to build before-kickoff, after-kickoff, and task callbacks. Hooks log safe metadata and optionally write status events, but they do not validate, mutate output, retry, prepare infrastructure, write artifacts, or send email.

`step_callback` remains deferred because CrewAI callback payloads are version-sensitive.

### Taxonomy Artifact as Source of Truth

Add `src/jee_tutor/curriculum` modules for taxonomy models, loading, caching, and validation. Runtime validation consumes only approved JSON from S3 or local file. Source PDFs are upstream material for a separate, explicitly approved taxonomy generation job.

Alternative considered: CrewAI Knowledge or runtime PDF parsing. That is useful context but not deterministic enough for a hard correctness gate.

### Status and Metrics

Reuse the existing invocation status store and safe logs for lifecycle evidence. Add status/metric events for CrewAI kickoff, task guardrail checks, retry categories, tool replay/re-execution, taxonomy load/validation, and artifact/response safety counters. Full diagnosis JSON, invalid output, image data URIs, base64 payloads, and recipient email must not be logged.

## Risks / Trade-offs

- CrewAI guardrail callable shape may vary by framework version -> add focused compatibility tests around pinned CrewAI `0.150.0`.
- A guardrail retry may require a higher orchestration call budget -> find the smallest budget through tests, then encode it in config/factories.
- Taxonomy validation can reject otherwise useful model output -> make fail-open available for local development, but production should fail closed when taxonomy is required.
- S3 taxonomy reload can fail after a good cache exists -> keep serving the last valid cached taxonomy and emit reload-failure telemetry.
- Moving correctness validation into the task guardrail can expose hidden assumptions in post-workflow rendering -> keep rendering deterministic and parse guardrail-approved JSON instead of revalidating the same contract.
- The taxonomy generation job may be mistaken for approval -> require explicit publish approval and schema/sanity checks before writing the approved S3 object.

## Migration Plan

1. Add task guardrail and tests while keeping current post-workflow validation as a temporary safety net.
2. Wire `Task.guardrail` with `max_retries=1` and prove guardrail execution on every CrewAI/ReAct diagnosis task.
3. Extend tool state for rejected observations and one semantic retry; add tests for finalization retry, semantic retry, and exhausted retry.
4. Add CrewAI hooks and safe telemetry tests.
5. Add taxonomy models, loader, validator, and generation script behind configuration.
6. Integrate taxonomy validation into the task guardrail.
7. Remove duplicate post-workflow correctness validation for the CrewAI/ReAct path once guardrail coverage metrics and tests prove equivalent or stricter behavior.
8. Extend CI/CD gates for controlled ReAct, taxonomy validation, and taxonomy generation publish controls.

Rollback is configuration-based for taxonomy validation when fail-open is allowed locally. The task guardrail and controlled ReAct changes should be rolled back together because retry semantics depend on shared tool state.

## Open Questions

- What exact orchestration call budget does CrewAI `0.150.0` need for forced first tool action, final answer, and one guardrail retry?
- Should recipient email remain stored plaintext in invocation status, or should this change also hash/redact it in the status store?
- Which taxonomy version should be the first approved production artifact?
