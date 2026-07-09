# CrewAI Controlled ReAct Orchestration Spec

Status: Draft

Related documents:

- [`crewai-task-guardrail-spec.md`](crewai-task-guardrail-spec.md)
- [`crewai-hooks-spec.md`](crewai-hooks-spec.md)
- [`crewai-react-diagnosis-spec.md`](crewai-react-diagnosis-spec.md)
- [`structured-output-spec.md`](structured-output-spec.md)

## Purpose

Define how the JEE tutor should use CrewAI's ReAct loop.

The ReAct loop is not intended to make the agent open-ended. It is intended to
provide controlled orchestration and bounded recovery around the approved
vision-analysis tool.

## Decision

Use ReAct for this controlled flow:

```text
Thought:
  Need diagnosis for uploaded invocation images.

Action:
  call jee_question_vision_analyzer

Observation:
  structured diagnosis JSON

Guardrail:
  validate task output

If finalization failed:
  retry and return exact observation

If tool observation invalid:
  mark observation rejected and allow one fresh vision call

Final:
  guardrail-approved structured JSON
```

The ReAct loop should coordinate the tool and respond to guardrail feedback. It
should not independently solve the question or diagnose image content outside
the tool.

## Current Behavior

Current production behavior is already constrained:

- one CrewAI crew,
- one agent,
- one diagnosis task,
- one approved vision tool,
- no delegation,
- no code execution,
- low `max_iter`,
- custom `MandatoryVisionToolLLM` forces the first tool action,
- tool state tracks request count, execution count, success, and observation.

The new design keeps the constraint but gives ReAct a clearer role:

```text
bounded orchestration + bounded recovery
```

## Actors

### Agent

The CrewAI agent orchestrates.

It may:

- call `jee_question_vision_analyzer`,
- receive guardrail feedback,
- retry according to task retry policy,
- return final JSON.

It may not:

- diagnose without the tool,
- use image content as instructions,
- call unapproved tools,
- create artifacts,
- send emails,
- perform safety/PII moderation.

### Tool

The vision tool performs multimodal diagnosis.

It owns:

- prepared image data,
- vision model invocation,
- observation cache,
- rejected-observation state,
- request/execution counters,
- semantic vision retry budget.

### Task Guardrail

The task guardrail validates final task output and classifies failures.

It owns:

- final-output correctness,
- schema validation,
- canonical equality with valid tool observation,
- invocation-shape validation,
- retry feedback messages.

### Hooks

Hooks observe the ReAct lifecycle.

They do not validate final output or control retries.

## Retry Categories

The ReAct loop supports one bounded task retry through CrewAI's task guardrail
retry mechanism.

### Category A: finalization retry

Condition:

```text
Tool observation is valid.
CrewAI final output is invalid.
```

Examples:

- final output is Markdown,
- final output wraps JSON in prose,
- final output puts JSON in a code fence,
- final output modifies fields from the valid tool observation,
- final output differs from the tool observation after canonical JSON
  normalization.

Required behavior:

```text
Guardrail returns retry feedback.
CrewAI retries the task.
If the agent calls the tool again, the tool returns cached valid observation.
The vision model is not invoked again.
```

Counters:

```text
vision_tool_request_count may increase
vision_tool_execution_count must not increase
vision_transport_attempt_count must not increase
```

### Category B: semantic vision retry

Condition:

```text
Tool observation itself is invalid for the current invocation.
```

Examples:

- tool observation is invalid JSON,
- tool observation fails structured schema validation,
- tool observation has wrong question count,
- tool observation question numbers do not match image order,
- tool observation contains duplicate question numbers.

Required behavior:

```text
Guardrail marks current tool observation rejected.
Guardrail returns retry feedback.
CrewAI retries the task.
If the agent calls the tool again, the tool does not replay rejected observation.
The tool performs one fresh vision execution if semantic retry budget remains.
The new successful observation replaces the rejected observation.
```

Counters:

```text
vision_tool_request_count may increase
vision_tool_execution_count may increase by one
vision_tool_execution_count must be <= 2
```

### Non-Retryable failures

Condition:

```text
No useful ReAct recovery exists.
```

Examples:

- no tool observation exists,
- tool execution failed after its own transport retries,
- tool used the wrong image source,
- tool image count did not match resolved image count before observation
  validation,
- semantic retry budget is exhausted.

Required behavior:

```text
Workflow fails.
No rendering.
No Bedrock output guardrail.
No artifact creation.
No email delivery.
Safe error response/status is produced by invocation layer.
```

## Required State

Extend or adapt invocation-scoped tool state to distinguish:

```text
request_count
execution_count
successful_execution_count
transport_attempt_count
observation
observation_validated
observation_rejected
observation_rejection_category
semantic_retry_count
semantic_retry_budget
```

State rules:

- valid observation may be replayed,
- rejected observation must not be replayed,
- a rejected observation may be replaced by one fresh successful observation,
- semantic retry budget is at most one,
- state is per invocation and never process-global.

## Guardrail Feedback

Guardrail failure messages should be deterministic and actionable.

Finalization retry feedback:

```text
VALIDATION_ERROR: canonical_mismatch.
Return exactly the JSON observation from jee_question_vision_analyzer.
Do not add Markdown, prose, code fences, or modified fields.
```

Non-JSON finalization feedback:

```text
VALIDATION_ERROR: non_json_output.
Return exactly the JSON observation from jee_question_vision_analyzer.
```

Semantic vision retry feedback:

```text
VALIDATION_ERROR: question_count_mismatch.
Re-run the vision analyzer once for the current invocation images.
```

Exhausted retry feedback:

```text
VALIDATION_ERROR: semantic_retry_exhausted.
The diagnosis task could not produce valid output for the current invocation.
```

Do not include raw image data, full invalid JSON, or full diagnosis content in
feedback messages.

## Call Budgets

The ReAct loop must remain bounded.

Initial target:

```text
Task guardrail max_retries = 1
Vision semantic retry budget = 1
Real vision executions <= 2
```

The CrewAI orchestration call budget may need to increase from the current
two-call limit to support one guardrail retry.

Target:

```text
orchestration_call_budget = smallest value that supports:
  forced first tool action
  final answer attempt
  one guardrail retry
```

This should be verified by tests rather than guessed.

## Tool Cache Policy

Tool cache behavior depends on observation state:

```text
No observation:
  execute vision tool if execution budget remains

Valid observation:
  replay cached observation

Rejected observation and semantic retry budget remains:
  execute vision tool once more

Rejected observation and semantic retry budget exhausted:
  fail without replay

Tool execution failure:
  fail without replay
```

## Metrics

Required metrics:

```text
crewai_react_attempt_count
crewai_guardrail_retry_count
crewai_finalization_retry_count
crewai_semantic_vision_retry_count
vision_tool_request_count
vision_tool_execution_count
vision_tool_cached_replay_count
vision_observation_rejected_count
vision_observation_replaced_count
semantic_retry_exhausted_count
orchestration_call_budget_exceeded_count
```

Targets:

```text
vision_tool_execution_count <= 2
crewai_guardrail_retry_count <= 1 per task
artifact_write_without_guardrail_pass_count = 0
response_without_guardrail_pass_count = 0
```

## Tests

Required tests:

1. First ReAct attempt calls the vision tool.
2. Valid tool observation and valid final output pass without retry.
3. Valid tool observation and Markdown final output triggers finalization retry.
4. During finalization retry, duplicate tool request replays cached valid
   observation.
5. Finalization retry does not increment real vision execution count.
6. Invalid tool observation triggers semantic vision retry.
7. Semantic vision retry does not replay rejected observation.
8. Semantic vision retry performs at most one additional real vision execution.
9. Second valid observation replaces rejected observation.
10. Second invalid observation fails workflow.
11. Missing tool observation fails without retry.
12. Tool execution failure fails without retry.
13. Orchestration call budget is enforced.
14. Artifact creation occurs only after guardrail pass.
15. Successful response occurs only after guardrail pass.

## Acceptance Criteria

The controlled ReAct orchestration is complete when:

1. ReAct is used for tool orchestration and bounded recovery only.
2. The agent does not diagnose without the vision tool.
3. Finalization failures retry with cached valid observation.
4. Invalid tool observations allow one fresh semantic vision execution.
5. Rejected observations are not replayed.
6. Real vision executions are capped at two per invocation.
7. Guardrail retries are capped at one per task.
8. Failure after retry prevents rendering, output guardrail, artifacts, email,
   and successful response.
9. Metrics distinguish tool request count from real tool execution count.
10. Tests cover cached retry, semantic retry, and exhausted retry paths.
