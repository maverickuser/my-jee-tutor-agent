# Agent Invocation Status Spec

Status: Draft

## Goal

Track each agent invocation as a single logical record with nested LLM call history.

This gives us:
- a stable invocation id
- idempotency-aware replay handling
- lifecycle status visibility
- per-LLM-call observability for batched image analysis

## Data model

Use one schema:

- `AgentInvocationRecord`
  - top-level lifecycle for the whole request
  - includes a nested `llm_calls` array

No separate child table is required for the first version.

## Top-level fields

### `invocation_id`

Unique internal id for one logical invocation.

Purpose:
- identifies the run internally
- links logs, artifacts, and email delivery

### `idempotency_key`

Stable caller-provided key used to dedupe/replay the same logical request.

Purpose:
- prevents duplicate logical invocations
- lets a retry return the prior result

### `status`

Overall invocation status.

Allowed values:
- `RECEIVED`
- `VALIDATED`
- `IN_PROGRESS`
- `SUCCEEDED`
- `FAILED`
- `REPLAYED`
- `BLOCKED`

Meaning:
- `RECEIVED`: request arrived
- `VALIDATED`: request payload passed validation
- `IN_PROGRESS`: workflow is running
- `SUCCEEDED`: terminal success
- `FAILED`: terminal failure after execution error
- `REPLAYED`: duplicate idempotent request returned prior result
- `BLOCKED`: request was intentionally stopped by guardrail, validation, or policy

### `status_reason`

Short human-readable explanation for the current status.

Examples:
- `Guardrail blocked`
- `Missing images`
- `Invalid payload`
- `Vision analysis failed`
- `Email delivery rejected`
- `Replayed from idempotency cache`

Rules:
- keep it short
- explain why, not how
- do not store stack traces here

### `subject`

Normalized JEE subject for the invocation.

Allowed values:
- `Maths`
- `Physics`
- `Chemistry`
- `null` if not available

### `image_count`

Total number of resolved images in the invocation.

Purpose:
- supports batching
- helps explain total processing cost

Rule:
- store the resolved count actually processed

### `recipient_email`

Optional email address to receive the analysis PDF.

Examples:
- `sociusnest@gmail.com`
- `analysis@konceptai.com`
- `null`

### `created_at`

Timestamp when the invocation record was created.

Rule:
- set once

### `updated_at`

Timestamp of the last update to the invocation record.

Rule:
- update whenever status or nested call state changes

### `completed_at`

Timestamp when the invocation reaches a terminal state.

Terminal states:
- `SUCCEEDED`
- `FAILED`
- `REPLAYED`
- `BLOCKED`

Rule:
- set once when terminal
- remain `null` while active

### `runtime_commit_sha`

Code version that handled the invocation.

Examples:
- a git SHA
- `unknown`

### `analysis_pdf_uri`

S3 URI of the generated analysis PDF, if created.

Example:
- `s3://bucket/path/Maths_analysis.pdf`

Rule:
- nullable
- set only on successful PDF creation

### `email_delivery_id`

Identifier for the email delivery attempt associated with the invocation.

Rule:
- nullable
- set only if email delivery is triggered

### `error_type`

Machine-readable failure class.

Examples:
- `TimeoutError`
- `MessageRejected`
- `OutputValidationError`
- `GuardrailBlockedError`

Rule:
- nullable
- set on `FAILED` and optionally on `BLOCKED`

### `error_message`

Short human-readable failure detail.

Examples:
- `Vision analyzer timed out after 180 seconds`
- `Email address is not verified`
- `CrewAI final output was invalid`

Rule:
- keep it short
- do not store full traces

### `llm_calls`

Nested list of every LLM call made during the invocation.

Purpose:
- one invocation can contain multiple vision batches
- CrewAI can add a final formatting call
- this is where latency, retries, and failures become visible

## `llm_calls[]` fields

### `llm_call_id`

Unique id for one model call inside the invocation.

Rule:
- unique within the invocation

### `batch_index`

Zero-based index of the call within its batch sequence.

Examples:
- first vision batch: `0`
- second vision batch: `1`

Rule:
- use a consistent ordering policy

### `batch_size`

Number of images included in that call.

Examples:
- `3`
- `2`
- `1`

Rule:
- for vision calls, this is the batch size
- for non-vision calls like CrewAI formatting, use `0` or `null`

### `model`

Resolved model used for the call.

Examples:
- `gemini/gemini-2.5-pro`
- `gemini/gemini-3-flash-preview`

### `provider`

Provider family for the call.

Examples:
- `gemini`
- `openai`
- `bedrock`

### `purpose`

Why the call happened.

Suggested values:
- `vision_analysis`
- `crewai_formatting`
- `guardrail_check`
- `other`

### `status`

Status of the individual LLM call.

Allowed values:
- `STARTED`
- `SUCCEEDED`
- `FAILED`
- `RETRIED`

### `attempt_number`

Retry attempt number for this call.

Rule:
- starts at `1`
- increments on retry

### `started_at`

Timestamp when the LLM call began.

### `ended_at`

Timestamp when the LLM call finished.

### `duration_ms`

Elapsed time for the LLM call in milliseconds.

Rule:
- derived from `ended_at - started_at`

### Optional telemetry fields

- `input_tokens`
- `output_tokens`
- `error_type`
- `error_message`
- `response_summary`

Rules:
- keep them optional
- do not store the full response body in status storage
- use `response_summary` only for a short safe summary or hash

## Lifecycle rules

The invocation record should move monotonically where possible:

1. `RECEIVED`
2. `VALIDATED`
3. `IN_PROGRESS`
4. one or more `llm_calls`
5. terminal state:
   - `SUCCEEDED`
   - `FAILED`
   - `REPLAYED`
   - `BLOCKED`

Idempotency rules:
- one logical invocation per `idempotency_key`
- repeated requests with the same key must not create duplicate logical work
- replayed requests should return the existing result and mark the record `REPLAYED`

## Why this shape

This schema keeps the model simple while still capturing:
- one logical agent request
- multiple batched LLM calls
- model-specific behavior
- retries and failures
- email linkage
- PDF output linkage

It is intentionally single-record first, with enough structure to split out child records later if volume requires it.
