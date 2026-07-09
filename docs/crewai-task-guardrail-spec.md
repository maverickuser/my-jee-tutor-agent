# CrewAI Task Guardrail Implementation Spec

Status: Final Draft

Related documents:

- [`crewai-react-diagnosis-spec.md`](crewai-react-diagnosis-spec.md)
- [`crewai-controlled-react-orchestration-spec.md`](crewai-controlled-react-orchestration-spec.md)
- [`structured-output-spec.md`](structured-output-spec.md)

## Purpose

Add a deterministic CrewAI task guardrail that answers one question:

```text
Did the CrewAI agent produce the correct kind of task output?
```

This guardrail is about workflow correctness. It is not a safety, PII, or
content-policy guardrail.

## Decision

Implement the CrewAI guardrail as deterministic Python code attached to the
diagnosis `Task`.

Do not implement this as an LLM-based guardrail.

Reason:

- The checks are objective.
- The expected output contract is known.
- A code guardrail is cheaper, faster, testable, and deterministic.
- An LLM guardrail would add latency, cost, nondeterminism, and another failure
  mode.

## Scope

### In Scope

The CrewAI task guardrail validates that:

1. The task output exists.
2. The task output is JSON, not Markdown or commentary.
3. The vision tool produced an observation.
4. The final task output matches the vision tool observation.
5. The output conforms to the structured diagnosis schema.
6. The output question count matches the resolved invocation image count.
7. The output matches expected question numbers when available.

### Out of Scope

The CrewAI task guardrail does not:

- detect PII,
- moderate unsafe content,
- inspect images for safety,
- replace Bedrock `ApplyGuardrail`,
- call another LLM,
- repair invalid output,
- perform S3, SES, DynamoDB, or artifact operations.

## Guardrail Layering

The system has two different guardrail types:

```text
Bedrock Runtime Guardrail
  Purpose: safety, PII, policy intervention
  Location: invocation boundary
  Implementation: Bedrock ApplyGuardrail

CrewAI Task Guardrail
  Purpose: task correctness
  Location: diagnosis Task
  Implementation: deterministic Python function
```

Both should exist. One does not replace the other.

## Current Gap

The current `diagnosis_task` has:

```python
Task(
    description=description,
    expected_output=STRUCTURED_OBSERVATION_EXPECTED_OUTPUT,
    agent=tutor_agent,
    tools=[vision_tool],
)
```

The task describes the required output, but it does not programmatically
validate it inside CrewAI.

Current validation happens after `crew.kickoff()` in `run_tutor_workflow(...)`.
The target design moves final task-output correctness validation into the CrewAI
task guardrail and removes the duplicate post-workflow validation for the
CrewAI/ReAct path.

After the guardrail passes, post-workflow code may parse the already-validated
JSON for rendering, but it should not re-run the same correctness checks as a
second validation gate.

## Target Design

Add a new module:

```text
src/jee_tutor/agent/task_guardrails.py
```

It should expose a factory function that builds the task guardrail with the
invocation-scoped state it needs:

```python
def build_diagnosis_task_guardrail(
    *,
    tool_call_state: VisionToolCallState,
    expected_image_count: int,
    expected_question_numbers: list[str | None] | None = None,
) -> Callable[[object], tuple[bool, str]]:
    ...
```

The factory returns a CrewAI-compatible guardrail callable:

```python
def diagnosis_task_guardrail(output: object) -> tuple[bool, str]:
    ...
```

## Validation Rules

The guardrail should evaluate rules in this order.

### 1. Output exists

Fail if the task output is missing or empty.

Failure message:

```text
Diagnosis task returned empty output.
```

### 2. Vision tool was called successfully

Fail if the tool state does not show a successful observation.

Failure message:

```text
Diagnosis task completed without a successful vision tool observation.
```

### 3. Output is JSON

Fail if the task output does not start as a JSON object.

Failure message:

```text
Diagnosis task must return structured JSON from the vision tool.
```

The guardrail should reject:

- Markdown,
- prose explanations,
- fenced code blocks,
- JSON with surrounding commentary.

### 4. Output matches tool observation

Fail if the final task output differs from the memoized tool observation.

Failure message:

```text
Diagnosis task output differs from the vision tool observation.
```

Comparison should use canonical JSON normalization, not raw string equality.
Whitespace differences should not fail the guardrail.

Field additions, field removals, reordered arrays, changed strings, or changed
values should fail.

### 5. Output matches structured diagnosis schema

Fail if parsing or schema validation fails.

This check verifies that the output has the required data shape:

- top-level `questions` list exists,
- each question has the required diagnosis fields,
- no extra fields are present,
- required strings are non-empty,
- field types are valid.

Failure message:

```text
Diagnosis task output failed schema validation: <safe error summary>
```

Validation should reuse the existing structured diagnosis parser:

```python
parse_and_validate_diagnosis(...)
```

### 6. Output matches expected invocation shape

Fail if the diagnosis does not match the current invocation shape.

This is separate from schema validation. A response can be schema-valid but
still wrong for this invocation.

Required checks:

- `len(diagnosis.questions) == expected_image_count`
- each diagnosis item corresponds to one resolved invocation image
- when expected question numbers are available, diagnosis question numbers
  match those expected numbers in image order

For this JSON-only task guardrail, `diagnosis.questions` is the structured
equivalent of final-output rows. Therefore this check enforces:

```text
resolved image count == final output question/row count
```

This should reuse the same validation semantics as the post-workflow structured
output path, but the CrewAI task guardrail becomes the authoritative validation
point for CrewAI/ReAct task output.

## Validation Ownership

For the CrewAI/ReAct path, the deterministic `Task.guardrail` owns final
task-output correctness.

Post-workflow code should not duplicate these same checks:

- final output equals tool observation,
- output is structured JSON,
- schema is valid,
- question count equals resolved image count,
- expected question numbers match.

Instead, post-workflow code should consume the guardrail-approved output and
continue with deterministic rendering, Bedrock output guardrail, artifact
creation, email delivery, status updates, and response formatting.

If the non-CrewAI direct path remains supported, it may keep its own validation
because it does not execute the CrewAI `Task.guardrail`.

## Retry Policy

Allow one bounded CrewAI task guardrail retry:

```python
max_retries=1
```

Reason:

- CrewAI guardrail retry feedback is useful when the tool observation is valid
  but the CrewAI final answer is malformed.
- The vision tool is invocation-scoped and can distinguish cached replay from a
  fresh semantic retry.
- External API retries are already handled by `idempotency_key`; this retry
  policy only covers one in-flight CrewAI/ReAct invocation.

The retry policy has two categories.

### Category A: finalization retry with cached tool observation

Use cached tool observation when the vision tool observation is valid but the
CrewAI final task output is wrong.

Examples:

- final output is Markdown,
- final output has prose or code fences around JSON,
- final output differs from a schema-valid tool observation,
- final output changes whitespace or formatting in a way that is not canonical
  JSON equivalent.

For this category:

```text
tool request count may increase
vision tool execution count must not increase
vision transport attempt count must not increase
```

If CrewAI calls `jee_question_vision_analyzer` again during the retry, the tool
returns the cached valid observation.

### Category B: semantic vision retry with cache invalidation

Allow one fresh vision execution when the tool observation itself is invalid for
the current invocation.

Examples:

- tool observation is invalid JSON,
- tool observation fails schema validation,
- tool observation has the wrong question count,
- tool observation question numbers do not match expected image order,
- tool observation contains duplicate question numbers.

For this category:

```text
first observation is marked rejected
cached observation is not replayed
CrewAI retry may call the vision tool again
vision tool may execute one more time
vision tool execution count must be <= 2
```

The second successful observation replaces the rejected observation. If the
second observation fails the guardrail, the workflow fails.

### Non-retryable failures

Do not retry when there is no useful corrective action:

- missing tool observation,
- tool execution failed after its own transport retry policy,
- tool did not use preloaded invocation images,
- tool image count did not match resolved image count before an observation was
  produced.

These failures should fail the workflow immediately.

## Task Wiring

Update `build_diagnosis_task(...)` so the task receives a guardrail.

Target shape:

```python
guardrail = build_diagnosis_task_guardrail(
    tool_call_state=vision_tool.call_state,
    expected_image_count=len(vision_tool.preloaded_image_data_uris),
    expected_question_numbers=vision_tool.expected_question_numbers,
)

return Task(
    description=description,
    expected_output=STRUCTURED_OBSERVATION_EXPECTED_OUTPUT,
    agent=tutor_agent,
    tools=[vision_tool],
    guardrail=guardrail,
    max_retries=1,
)
```

If `expected_image_count` cannot be reliably derived from the tool instance at
task construction time, pass it explicitly into `build_diagnosis_task(...)`.

## Pseudocode

```python
def build_diagnosis_task_guardrail(
    *,
    tool_call_state: VisionToolCallState,
    expected_image_count: int,
    expected_question_numbers: list[str | None] | None = None,
):
    def guardrail(output: object) -> tuple[bool, str]:
        raw = extract_task_output_text(output)
        if not raw:
            return False, "Diagnosis task returned empty output."

        if not tool_call_state.success or not tool_call_state.observation:
            return (
                False,
                "Diagnosis task completed without a successful vision tool observation.",
            )

        if not raw.lstrip().startswith("{"):
            return (
                False,
                "VALIDATION_ERROR: non_json_output. Return exactly the JSON "
                "observation from jee_question_vision_analyzer.",
            )

        observation_validation = validate_tool_observation(
            tool_call_state.observation,
            expected_image_count=expected_image_count,
            expected_question_numbers=expected_question_numbers,
        )
        if not observation_validation.valid:
            tool_call_state.reject_observation(observation_validation.failure_category)
            return (
                False,
                "VALIDATION_ERROR: "
                f"{observation_validation.failure_category}. Re-run the vision analyzer "
                "once for the current invocation images.",
            )

        try:
            canonical_output = canonical_json(raw)
        except Exception as exc:
            return False, f"Diagnosis task output failed schema validation: {safe_summary(exc)}"

        if canonical_output != canonical_json(tool_call_state.observation):
            return (
                False,
                "VALIDATION_ERROR: canonical_mismatch. Return exactly the JSON "
                "observation from jee_question_vision_analyzer.",
            )

        return True, raw

    return guardrail
```

The concrete implementation may combine `validate_tool_observation(...)` with
the existing `parse_and_validate_diagnosis(...)`; the key requirement is that
the guardrail can classify whether failure belongs to:

- finalization retry with cached observation,
- semantic vision retry with cache invalidation,
- non-retryable failure.

## Output Extraction

The guardrail should tolerate CrewAI output wrapper types.

Suggested extraction order:

1. `output.raw` if present and string-like.
2. `str(output)` fallback.

Do not inspect or log full output on failure. Error messages should be safe and
short.

## Canonical JSON Comparison

Use deterministic JSON normalization:

```python
json.dumps(json.loads(value), sort_keys=True, separators=(",", ":"))
```

If either value is invalid JSON, fail with the appropriate JSON/schema error.

Important: JSON object key order should not matter. Array order should matter.
Question ordering is semantically meaningful.

## Error Handling

The guardrail should return `(False, message)` for expected validation failures.

It should avoid raising exceptions except for unexpected programmer errors.

Messages should be:

- deterministic,
- safe for logs,
- short,
- specific enough for debugging.

## Observability

Emit a metric or structured log event every time the CrewAI task guardrail runs.

Required fields:

- `event = "crewai_task_guardrail_check"`
- `invocation_id`
- `task_name = "diagnosis_task"`
- `guardrail_name = "diagnosis_task_output_contract"`
- `result = "passed" | "failed"`
- `failure_category`, when failed
- `expected_image_count`
- `actual_question_count`, when parseable
- `expected_question_number_count`
- `actual_question_number_count`, when parseable
- `tool_call_count`
- `tool_execution_count`
- `tool_success`
- `tool_observation_present`
- `canonical_match`, when both final output and observation are valid JSON
- `schema_valid`, when JSON parsing succeeds
- `retry_category = "cached_finalization_retry" | "semantic_vision_retry" | "non_retryable" | null`
- `vision_retry_budget_remaining`

When the guardrail fails, log metadata only:

- invocation id if available,
- failure category,
- whether tool observation existed,
- tool call count,
- tool execution count,
- expected image count,
- expected question numbers count.

Do not log:

- image payloads,
- full diagnosis JSON,
- full invalid output.

## Proof Metrics

The guardrail is considered proven when CI, CD, and production telemetry show
that the guardrail is always executed for the CrewAI/ReAct path and is the only
task-output correctness gate.

Track these metrics:

### Coverage metric

```text
crewai_guardrail_execution_rate =
  guardrail_check_count / crewai_diagnosis_task_completed_count
```

Target:

```text
100%
```

Every completed CrewAI diagnosis task must have at least one guardrail check.
No-retry tasks should have exactly one guardrail check. If a guardrail retry
occurs, the task may have more than one guardrail check. Track both:

```text
crewai_guardrail_check_count
crewai_guardrail_attempt_count_per_task
```

Target:

```text
crewai_guardrail_attempt_count_per_task <= 2
```

### Pass/fail metric

```text
crewai_guardrail_pass_count
crewai_guardrail_fail_count
crewai_guardrail_failure_category_count
```

Failure categories should include:

- `empty_output`
- `missing_tool_observation`
- `non_json_output`
- `canonical_mismatch`
- `schema_invalid`
- `question_count_mismatch`
- `question_number_mismatch`
- `duplicate_question_number`

Retry categories should include:

- `cached_finalization_retry`
- `semantic_vision_retry`
- `non_retryable`

Vision retry metrics:

```text
vision_semantic_retry_count
vision_observation_rejected_count
vision_tool_execution_count_after_retry
```

Targets:

```text
vision_tool_execution_count_after_retry <= 2
```

### Bypass metric

```text
post_workflow_duplicate_validation_count
```

Target for CrewAI/ReAct path:

```text
0
```

This proves the old duplicate validation path is not still acting as a hidden
second gate.

### Artifact safety metric

```text
artifact_write_after_guardrail_pass_count
artifact_write_without_guardrail_pass_count
```

Target:

```text
artifact_write_without_guardrail_pass_count = 0
```

PDF/Markdown artifacts must only be created after a successful task guardrail.

### Response safety metric

```text
response_after_guardrail_pass_count
response_without_guardrail_pass_count
```

Target for successful CrewAI/ReAct responses:

```text
response_without_guardrail_pass_count = 0
```

Successful responses must only use guardrail-approved task output.

### Regression metric

CI tests should include negative fixtures proving each failure category blocks
the task before rendering or artifact creation.

Production telemetry should be monitored for:

- guardrail execution rate below 100%,
- artifact writes without guardrail pass,
- successful responses without guardrail pass,
- unexpected failure categories.

## Tests

Add tests for the task guardrail module.

Required cases:

1. Valid output matching the tool observation passes.
2. Empty output fails.
3. Markdown output fails.
4. JSON with surrounding commentary fails.
5. Missing tool observation fails.
6. Tool failure state fails.
7. Output JSON differing from tool observation fails.
8. Whitespace-only JSON differences pass.
9. JSON object key order differences pass.
10. JSON array order differences fail.
11. Schema-invalid JSON fails.
12. Wrong expected image count fails.
13. Wrong expected question number fails.
14. Finalization failure with valid tool observation retries using cached
    observation.
15. Invalid tool observation marks the observation rejected and allows one fresh
    vision execution.
16. A second invalid vision observation fails the workflow.
17. A semantic vision retry never exceeds two real vision executions.

Add wiring tests:

1. `build_diagnosis_task(...)` attaches a guardrail.
2. `build_diagnosis_task(...)` sets `max_retries=1`.
3. CrewAI/ReAct success path records exactly one guardrail check when no retry
   occurs.
4. CrewAI/ReAct success path does not run duplicate post-workflow correctness
   validation.
5. Artifact creation is skipped when the task guardrail fails.
6. Successful artifact creation requires a recorded guardrail pass.
7. Guardrail retry attempts are capped at two total guardrail checks per task.

## Acceptance Criteria

Implementation is complete when:

1. The diagnosis task has a deterministic CrewAI `Task.guardrail`.
2. The guardrail uses no LLM calls.
3. The guardrail enforces exact canonical JSON equality with the tool
   observation.
4. The guardrail validates structured diagnosis schema.
5. The guardrail validates expected invocation shape, including
   `resolved image count == final output question/row count`.
6. The task uses `max_retries=1`.
7. Bedrock runtime guardrails remain unchanged.
8. Duplicate post-workflow correctness validation is removed for the
   CrewAI/ReAct path.
9. Metrics prove the task guardrail executes once for successful no-retry tasks
   and at most twice for retried tasks.
10. Metrics prove artifacts and successful responses are produced only after a
    guardrail pass.
11. Metrics prove semantic vision retries never exceed two real vision tool
    executions.
12. Unit tests cover pass/fail behavior, task wiring, retry categorization,
    cache replay, one fresh vision retry, and no duplicate validation on the
    CrewAI/ReAct success path.
