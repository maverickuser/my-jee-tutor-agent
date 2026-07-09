# CrewAI Hooks Implementation Spec

Status: Draft

Related documents:

- [`crewai-task-guardrail-spec.md`](crewai-task-guardrail-spec.md)
- [`crewai-controlled-react-orchestration-spec.md`](crewai-controlled-react-orchestration-spec.md)
- [`crewai-react-diagnosis-spec.md`](crewai-react-diagnosis-spec.md)

## Purpose

Add CrewAI lifecycle hooks for observability and control-plane telemetry.

Hooks answer:

```text
What happened during CrewAI execution?
```

They do not answer:

```text
Is the final task output valid?
```

Final task-output correctness belongs to the deterministic CrewAI
`Task.guardrail` described in
[`crewai-task-guardrail-spec.md`](crewai-task-guardrail-spec.md).

## Decision

Use CrewAI hooks/callbacks for observability first.

Do not use hooks as the primary validation layer.

Initial implementation should use:

1. `before_kickoff_callbacks`
2. `after_kickoff_callbacks`
3. `task_callback`

Defer `step_callback` until the exact callback payload is verified for the
pinned CrewAI version.

## Non-Goals

Hooks must not:

- replace `Task.guardrail`,
- validate final diagnosis schema,
- compare final output with tool observation,
- perform Bedrock safety checks,
- resolve S3 image prefixes,
- decode raw user image input,
- write artifacts,
- send email,
- repair or rewrite model output,
- retry the workflow.

## Current Gap

Current Crew construction does not wire CrewAI hooks:

```python
Crew(
    agents=[tutor_agent],
    tasks=[diagnosis_task],
    process=Process.sequential,
    verbose=False,
)
```

The repo already has observability through logs, `VisionToolCallState`,
Langfuse, status store integration, and workflow-level counters. However,
CrewAI lifecycle events are not explicitly captured at CrewAI boundaries.

## Hook Responsibilities

### 1. `before_kickoff_callbacks`

Purpose:

```text
Record that CrewAI orchestration is starting.
```

Responsibilities:

- log `invocation_id`,
- log expected image count,
- log expected question number count,
- log CrewAI/ReAct mode,
- log crew/task/agent names,
- optionally write a status-store event such as `CREW_STARTED`.

This hook may assert that required prepared metadata is present. It should not
perform infrastructure preparation.

Must not:

- parse raw AgentCore payload,
- list or read S3 images,
- decode image payloads,
- call Bedrock Guardrails,
- mutate task output,
- run final-output validation.

### 2. `after_kickoff_callbacks`

Purpose:

```text
Record that CrewAI orchestration finished.
```

Responsibilities:

- log completion status,
- log output size metadata,
- log tool request count,
- log tool execution count,
- log tool success/failure state,
- log task guardrail result if available,
- log orchestration call count if available,
- optionally write a status-store event such as `CREW_COMPLETED`.

Must not:

- fix or rewrite output,
- retry the workflow,
- run duplicate task-output validation,
- create artifacts,
- send emails.

### 3. `task_callback`

Purpose:

```text
Record task-level completion.
```

Responsibilities:

- log task name,
- log task elapsed time if available,
- log output length only, not full output,
- log task guardrail pass/fail metadata if available,
- optionally write a status-store event such as `TASK_COMPLETED`.

Must not:

- replace the task guardrail,
- inspect image payloads,
- log full diagnosis JSON,
- log full invalid output.

### 4. `step_callback`

Status: deferred.

Potential purpose:

```text
Observe ReAct loop steps.
```

Potential responsibilities:

- count ReAct steps,
- record action names,
- detect whether the first action was `jee_question_vision_analyzer`,
- record unexpected actions as telemetry,
- emit `crewai_step_count`,
- emit `crewai_unexpected_action_count`.

Reason for deferral:

- callback payloads can be framework-version-sensitive,
- first-action enforcement currently exists through `MandatoryVisionToolLLM`,
- final task output correctness belongs to `Task.guardrail`,
- step callback should not be used as the first implementation's enforcement
  mechanism.

Before enabling `step_callback`, add a small compatibility test that captures
the callback object shape for CrewAI `0.150.0`.

## Proposed Module

Add:

```text
src/jee_tutor/agent/crew_callbacks.py
```

Suggested context object:

```python
@dataclass(frozen=True)
class CrewCallbackContext:
    invocation_id: str | None
    expected_image_count: int
    expected_question_numbers: list[str | None]
    tool_call_state: VisionToolCallState
    status_store: InvocationStatusStore | None = None
```

Suggested callback bundle:

```python
@dataclass(frozen=True)
class CrewCallbacks:
    before_kickoff_callbacks: list[Callable]
    after_kickoff_callbacks: list[Callable]
    task_callback: Callable | None = None
    step_callback: Callable | None = None
```

Factory:

```python
def build_crew_callbacks(context: CrewCallbackContext) -> CrewCallbacks:
    ...
```

## Crew Wiring

Target shape:

```python
callbacks = build_crew_callbacks(
    CrewCallbackContext(
        invocation_id=invocation_id,
        expected_image_count=len(image_data_uris or []),
        expected_question_numbers=expected_question_numbers or [],
        tool_call_state=tool_call_state,
        status_store=status_store,
    )
)

return Crew(
    agents=[tutor_agent],
    tasks=[diagnosis_task],
    process=Process.sequential,
    before_kickoff_callbacks=callbacks.before_kickoff_callbacks,
    after_kickoff_callbacks=callbacks.after_kickoff_callbacks,
    task_callback=callbacks.task_callback,
    verbose=False,
)
```

Do not wire `step_callback` in the first implementation.

## Failure Policy

Hooks should be side-effect-light.

Default policy:

```text
Observability failure should not fail diagnosis.
```

Examples:

- logger failure: do not fail diagnosis,
- status-store write failure: do not fail diagnosis,
- missing optional metadata: log safe warning and continue.

Exceptions:

- missing required invocation-prepared metadata may fail before kickoff,
  because that indicates a programming/configuration error.

Any hook exception that is swallowed must be logged safely.

## Metrics

Hooks should emit structured logs or metrics for:

```text
crewai_kickoff_started_count
crewai_kickoff_completed_count
crewai_task_completed_count
crewai_task_failed_count
crewai_tool_request_count
crewai_tool_execution_count
crewai_tool_success_count
crewai_tool_failure_count
crewai_guardrail_pass_count
crewai_guardrail_fail_count
```

Deferred step metrics:

```text
crewai_step_count
crewai_first_action_vision_tool_count
crewai_unexpected_action_count
```

## Logging Rules

Hooks may log metadata:

- invocation id,
- task name,
- crew name if available,
- expected image count,
- expected question number count,
- output length,
- tool call counters,
- guardrail result category.

Hooks must not log:

- image data URIs,
- raw base64 image payloads,
- full model output,
- full diagnosis JSON,
- full invalid output,
- recipient email.

## Tests

Required tests:

1. `build_crew_callbacks(...)` returns before/after/task callbacks.
2. `build_tutor_crew(...)` wires before-kickoff callbacks.
3. `build_tutor_crew(...)` wires after-kickoff callbacks.
4. `build_tutor_crew(...)` wires task callback.
5. `step_callback` is not wired in the initial implementation.
6. before-kickoff callback emits start metadata.
7. after-kickoff callback emits completion metadata.
8. task callback emits task metadata without logging full output.
9. status-store failure inside a hook does not fail diagnosis.
10. hook logs do not contain image payloads or recipient email.

Deferred tests for `step_callback`:

1. Capture callback payload shape for CrewAI `0.150.0`.
2. Record first action name when available.
3. Record unexpected action telemetry without replacing task guardrail behavior.

## Acceptance Criteria

The hook implementation is complete when:

1. CrewAI kickoff start is observable.
2. CrewAI kickoff completion is observable.
3. CrewAI task completion is observable.
4. Tool request/execution counters are emitted at CrewAI boundaries.
5. Task guardrail pass/fail counters are emitted when available.
6. Hook failures do not fail diagnosis except for explicit required metadata
   errors.
7. Hooks do not perform final-output validation.
8. Hooks do not perform infrastructure preparation.
9. Hooks do not log sensitive payloads.
10. `step_callback` remains deferred until payload compatibility is verified.
