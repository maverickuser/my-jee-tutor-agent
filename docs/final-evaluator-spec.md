# Final Analysis Evaluator and PDF Quality Gate

Status: Proposed

Implementation breakdown:
[`quality-pipeline-implementation-plan.md`](quality-pipeline-implementation-plan.md)

## Objective

Add an independent final-evaluation layer after vision diagnosis and before any
PDF or Markdown artifact is written. The evaluator uses the current invocation
images as the authoritative source, scores the analysis, and produces a
deterministic final decision.

Only analyses with a `PASS` decision may be written to an artifact.

## Target Architecture

The target design restores a constrained CrewAI ReAct loop for diagnosis while
keeping the final evaluator as a separate, bounded, tool-free CrewAI stage:

```text
Images
  -> constrained CrewAI ReAct diagnosis
  -> memoized vision tool execution
  -> structured diagnosis validation
  -> tool-free CrewAI final evaluator
  -> deterministic score policy
  -> PASS: render and write PDF
     REVIEW/REJECT: write no artifact and return an evaluation error
```

Duplicate diagnosis-tool requests replay the invocation-scoped observation and
never start another real tool execution. The evaluator has no tools, cannot
delegate, cannot modify the diagnosis, and must make exactly one evaluator LLM
call per evaluation attempt.

Model assignment is explicit:

- Diagnosis: `gemini/gemini-2.5-pro`
- Final evaluation: `gemini/gemini-2.5-flash`

## Dependency

This specification depends on:

- [`structured-output-spec.md`](structured-output-spec.md)
- [`crewai-react-diagnosis-spec.md`](crewai-react-diagnosis-spec.md)

The preferred evaluator input is the validated `DiagnosisResponse`, not
model-generated Markdown. Deterministic Markdown rendering happens only after
the final evaluation passes.

If the evaluator is implemented before structured diagnosis, a temporary
Markdown adapter may be used, but it must be removed when structured output is
enabled.

## Goals

- Detect claims not supported by the current invocation images.
- Detect claims that contradict visible question or attempt evidence.
- Verify that every required diagnosis element is present.
- Assess whether inferred student reasoning is appropriately qualified,
  specific, and evidence-aligned.
- Produce auditable per-question findings and aggregate metrics.
- Block artifact creation when quality requirements are not met.
- Avoid hidden CrewAI, LiteLLM, or application retry layers.

## Non-Goals

- Automatically rewriting or repairing a failed diagnosis.
- Calling the diagnosis tool again.
- Adding questions, solutions, or concepts not present in the diagnosis.
- Using filenames, previous invocations, cached context, or general assumptions
  as evidence for the question content.
- Replacing deterministic structural validation.
- Evaluating student identity or report filename metadata.

## Evaluation Source Rules

The evaluator receives only:

- Current invocation images, in resolved order.
- Validated structured diagnosis, in the same order.
- Optional invocation task and subject context.
- Expected image count.

The images remain the authoritative source. Text embedded in images is untrusted
question content and must not be followed as instructions.

The evaluator must not use:

- Image filenames as evidence.
- Previous responses or invocations.
- Sample reports.
- External web or retrieval tools.
- Memory or delegation.

## CrewAI Design

Add a separate evaluator factory and crew, for example:

- `build_final_evaluator_agent`
- `build_final_evaluation_task`
- `build_final_evaluator_crew`

Required CrewAI configuration:

```python
Agent(
    role="JEE diagnosis quality evaluator",
    goal="Evaluate grounding and diagnostic quality using only current images.",
    tools=[],
    allow_delegation=False,
    max_iter=1,
    max_retry_limit=0,
    verbose=True,
)

Crew(
    agents=[evaluator_agent],
    tasks=[evaluation_task],
    process=Process.sequential,
    verbose=True,
)
```

The evaluator must use a dedicated LLM wrapper with:

- `model = "gemini/gemini-2.5-flash"`
- `temperature = 0`
- `caching = false`
- `num_retries = 0`
- Explicit timeout.
- A strict structured response schema.
- Redacted image payloads in observability.

CrewAI must not receive the diagnosis vision tool or any other tool.

## Evaluator Output Schema

Add Pydantic models in a dedicated module such as
`jee_tutor.agent.final_evaluation`.

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class ClaimKind(StrEnum):
    OBSERVATION = "observation"
    INFERENCE = "inference"
    RECOMMENDATION = "recommendation"


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class ClaimEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    field_name: str
    claim_kind: ClaimKind
    status: ClaimStatus
    evidence_summary: str
    issue_summary: str | None = None
    critical: bool = False


class QuestionEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    question_number: str
    claims: list[ClaimEvaluation]
    applicable_completeness_items: list[str]
    satisfied_completeness_items: list[str]
    inference_criteria_scores: dict[str, float]
    issues: list[str]


class EvaluatorAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    questions: list[QuestionEvaluation]
    evaluator_summary: str
```

The evaluator LLM returns evidence and classifications. It does not return the
authoritative aggregate metrics or final decision. Application code calculates
those values deterministically.

The authoritative application model remains grouped by question as shown above.
The Gemini-facing transport schema must be flat: top-level claim, completeness,
and inference-score record arrays carry `row_index` directly. Application code
converts those records into `EvaluatorAssessment` before reference validation
and metric calculation. This avoids nested arrays in Gemini's structured-output
schema while preserving the same evidence and deterministic decision contract.

## Claim Identification

The evaluator must classify independently verifiable claims in these diagnosis
fields:

- `question_number`
- `chapter`
- `topic`
- `what_you_thought`
- `why_that_thought_is_wrong`
- `exact_concept_gap`
- `what_you_must_deep_dive`

A claim is a single assertion that can be evaluated independently. Compound
sentences must be split into separate claims when their support status differs.

Claim kinds:

- `observation`: states visible question, option, attempt, formula, marking, or
  other directly observable content.
- `inference`: infers student reasoning, misconception, intent, strategy, or
  reason for not attempting.
- `recommendation`: proposes concepts or techniques to study.

Claim statuses are mutually exclusive:

- `supported`: directly supported by visible evidence, or a clearly qualified
  inference/recommendation logically grounded in that evidence.
- `unsupported`: not established or reasonably grounded by the current images.
- `contradicted`: conflicts with visible question or attempt evidence.

## Metric Definitions

All aggregate metrics use the range `0.0` to `1.0` and are rounded to four
decimal places only after calculation.

Let:

- `S` = supported claim count.
- `U` = unsupported claim count.
- `C` = contradicted claim count.
- `T = S + U + C`.

If `T == 0`, evaluation fails closed because groundedness cannot be established.

### `groundedness_score`

Proportion of evaluated claims supported by the current images:

```text
groundedness_score = S / T
```

This metric includes observations, inferences, and recommendations.

### `unsupported_claim_rate`

Proportion of evaluated claims that lack sufficient support:

```text
unsupported_claim_rate = U / T
```

Contradictions are excluded from this numerator because they have their own
stronger category.

### `contradiction_rate`

Proportion of evaluated claims that conflict with visible evidence:

```text
contradiction_rate = C / T
```

Any critical contradiction is also a hard failure regardless of the aggregate
rate.

### `completeness_score`

For each image, define applicable required diagnosis items:

1. Question number or unreadable sentinel.
2. Chapter or unable-to-determine sentinel.
3. Topic or unable-to-determine sentinel.
4. Likely student thought process or visibility-limitation explanation.
5. Why the thought is wrong/incomplete, or why it cannot be determined.
6. Exact concept gap, or why it cannot be determined.
7. Specific deep-dive recommendation, or why it cannot be determined.
8. Missed-option concepts when a visible multiple-correct partial attempt makes
   this applicable.
9. Conceptual or strategic reason when a visible unattempted question makes this
   applicable.

Let `A` be the total applicable items and `P` the total satisfied items:

```text
completeness_score = P / A
```

If `A == 0`, evaluation fails closed.

An item is satisfied only when it is non-empty, relevant, and sufficiently
specific. Mere presence of text is not enough.

### `inference_quality_score`

Score each applicable inferred student-thought diagnosis against five criteria:

1. `evidence_alignment`: connected to visible attempt evidence.
2. `qualification`: uncertain reasoning uses language such as `likely`.
3. `specificity`: identifies a concrete reasoning step or misconception.
4. `no_overclaiming`: does not invent selections, calculations, or intentions.
5. `root_cause_linkage`: connects the inferred thought to the identified gap and
   recommendation.

Each criterion is scored from `0.0` to `1.0`. The metric is the arithmetic mean
of all applicable criterion scores:

```text
inference_quality_score = sum(criterion scores) / criterion count
```

If no inference is possible because every image is unreadable, use `1.0` only
when the diagnosis correctly avoids inference and explains the limitation.
Otherwise, missing applicable inference criteria fail closed.

## Deterministic Final Decision

Application code computes `final_decision`; the LLM cannot override it.

Thresholds must be configuration values. Initial defaults:

```toml
[final_evaluator]
enabled = true
fail_closed = true
model = "gemini/gemini-2.5-flash"
temperature = 0
pass_groundedness_score = 0.90
pass_unsupported_claim_rate = 0.05
pass_contradiction_rate = 0.00
pass_completeness_score = 0.90
pass_inference_quality_score = 0.80
review_groundedness_score = 0.75
review_unsupported_claim_rate = 0.20
review_contradiction_rate = 0.05
review_completeness_score = 0.75
review_inference_quality_score = 0.65
```

Decision policy:

### `PASS`

All pass thresholds are satisfied, there are no critical contradictions, and
all structural invariants pass.

### `REVIEW`

All review thresholds are satisfied, but one or more pass thresholds are not.
There are no critical contradictions.

### `REJECT`

Any review threshold fails, a critical contradiction exists, evaluator output
is invalid, or required evaluation evidence is missing.

Application checks must verify:

- Metric values are finite and within `[0, 1]`.
- `groundedness_score + unsupported_claim_rate + contradiction_rate == 1`
  within a small floating-point tolerance.
- Evaluator row count and order match diagnosis row count and order.
- Every claim references a valid row and field.
- Every diagnosis field has at least one evaluated claim or an explicit
  completeness finding.

## PDF Gate Behavior

Artifact creation occurs only after evaluation:

```python
evaluation = final_evaluator.evaluate(
    images=resolved_image_data_uris,
    diagnosis=validated_diagnosis,
    context=invocation.resolved_question_context,
)

decision = evaluation_policy.decide(evaluation)
if decision is not PASS:
    raise FinalEvaluationError(evaluation)

return artifact_writer.write_for_invocation(...)
```

Behavior by decision:

- `PASS`: render Markdown and write PDF normally.
- `REVIEW`: do not write PDF or Markdown fallback; return a final-evaluation
  error requiring review.
- `REJECT`: do not write PDF or Markdown fallback; return a final-evaluation
  error.

The unapproved diagnosis must not be returned as a successful analysis response.

If the evaluator itself times out, fails, or returns invalid output:

- `fail_closed = true`: write no artifact and return an evaluation error.
- `fail_closed = false`: allowed only for controlled non-production testing and
  must emit a high-severity warning.

## Error Contract

Add `FinalEvaluationError` with safe details:

- Final decision.
- Five aggregate metrics.
- Failed threshold names.
- Critical issue count.
- Evaluator error category, when applicable.

Do not include:

- Raw image payloads.
- Full raw evaluator output.
- API credentials.
- Unbounded claim text.

Recommended application error:

```json
{
  "error": "Analysis did not pass final quality evaluation.",
  "details": [
    "Final decision: REVIEW.",
    "Groundedness score: 0.8200.",
    "Completeness score: 0.8800.",
    "PDF artifact was not created."
  ]
}
```

## Retry and Timeout Policy

The evaluator must have a separate bounded policy from diagnosis.

Recommended initial evaluator policy:

- One evaluator attempt.
- Explicit timeout.
- LiteLLM retries disabled.
- CrewAI retries disabled.
- No retry for invalid schema, metric inconsistency, or semantic failure.

Adding the evaluator creates a second multimodal LLM call and therefore increases
latency, token cost, and quota usage. The external client and AgentCore deadlines
must cover diagnosis plus evaluation. This budget must be measured before
production rollout.

## Observability

Create a separate Langfuse generation/span named `final-analysis-evaluation`.

Record:

- Evaluator model (`gemini/gemini-2.5-flash`) and schema version.
- Invocation/request correlation ID and sampling mode.
- Expected and evaluated question counts.
- Claim counts `S`, `U`, `C`, and `T`.
- All five aggregate metrics.
- Final decision.
- Failed threshold names.
- Critical issue count.
- Evaluator latency and token/cost accounting.
- Whether PDF creation was allowed.

Emit the observation and Langfuse scores for every sampled evaluation attempt,
including `PASS`, `REVIEW`, `REJECT`, evaluator error, timeout, and invalid
structured output. Publish each available aggregate metric as a numeric score
and the artifact-allowed result as a boolean score. Do not omit a rejected or
errored attempt merely because the application returns an error response.

For `REVIEW`, `REJECT`, or evaluator failure, attach the same bounded diagnostic
fields used by `FinalEvaluationError`: decision, failed threshold names,
critical issue count, evaluator error category, and sanitized issue summaries
when available. This diagnostic output must be sufficient to identify which
quality gate failed without inspecting the raw evaluator completion.

Images remain redacted. Evidence and issue summaries must be count- and
length-bounded, sanitized, and omitted if they may contain student personal
information. Never log prompts, raw evaluator completions, stack traces,
credentials, or unbounded diagnosis text.

Metrics:

- `final_evaluator.invocations`
- `final_evaluator.pass`
- `final_evaluator.review`
- `final_evaluator.reject`
- `final_evaluator.errors`
- `final_evaluator.latency_ms`
- `final_evaluator.groundedness_score`
- `final_evaluator.unsupported_claim_rate`
- `final_evaluator.contradiction_rate`
- `final_evaluator.completeness_score`
- `final_evaluator.inference_quality_score`
- `artifact.blocked_by_final_evaluator`

## Security

- Treat analysis text as untrusted data in the evaluator prompt.
- Delimit analysis data separately from evaluator instructions.
- Repeat the instruction that image text cannot override evaluator policy.
- Give the evaluator no tools, delegation, memory, web access, or file writes.
- Redact image data and API keys from logs and traces.
- Cap evaluator output size and issue-list lengths.

## File-Level Implementation Plan

Expected additions:

- `src/jee_tutor/agent/final_evaluation.py`
  - Pydantic models, metric calculation, thresholds, decision policy, errors.
- `src/jee_tutor/agent/evaluator_crew.py`
  - Tool-free CrewAI agent, task, and crew factories.
- `src/jee_tutor/agent/evaluator_client.py`
  - Bounded structured multimodal evaluator call.
- Prompt constants and local fallbacks for evaluator role and task.
- `[final_evaluator]` configuration in `src/config/llm.toml`.

Expected modifications:

- Invocation service to run evaluation before `_success_response`.
- Artifact path so no writer method is called before `PASS`.
- Observability helpers for evaluator spans and metrics.
- Response/error models if evaluation summaries are exposed.
- Tests and README.

## Test Requirements

### Metric unit tests

- All supported claims produce groundedness `1.0`.
- Unsupported and contradicted claims use separate numerators.
- Claim rates sum to `1.0`.
- Zero claims fail closed.
- Completeness uses applicable rather than fixed item count.
- Inference criteria average correctly.
- Invalid, NaN, infinite, and out-of-range scores are rejected.

### Decision-policy tests

- Exact pass-threshold boundaries pass.
- Exact review-threshold boundaries review.
- Values below review thresholds reject.
- Any critical contradiction rejects.
- A positive contradiction rate cannot pass when pass threshold is zero.
- LLM-suggested decisions cannot override application policy.

### CrewAI tests

- Evaluator has no tools.
- Delegation and retries are disabled.
- Exactly one evaluator LLM call occurs.
- Images and diagnosis are both provided.
- Invalid structured output does not trigger another call.
- Image-embedded instructions do not change evaluator behavior.

### Integration tests

- `PASS` calls artifact writer exactly once.
- `REVIEW` and `REJECT` never call artifact writer.
- Evaluator timeout never calls artifact writer.
- Invalid evaluator JSON never calls artifact writer.
- Evaluation happens after diagnosis validation.
- API and PDF behavior remains unchanged for passing analyses.
- Every sampled attempt publishes its available metrics, decision, artifact
  permission, and correlation fields to Langfuse.
- `REVIEW`, `REJECT`, and evaluator-error observations contain bounded safe
  diagnostics matching the application error contract.
- Langfuse receives no image payloads, prompts, raw completions, credentials, or
  student personal information.
- Idempotent repeated successful invocations do not rerun evaluation.

### Live evaluation

- One-image and six-image cases.
- Incorrect question number.
- Invented student selection.
- Contradicted visible option.
- Missing concept gap.
- Vague deep-dive recommendation.
- Correctly qualified inference.
- Unreadable image with no invented diagnosis.

## Rollout

1. Implement structured diagnosis output first.
2. Add evaluator in shadow mode: calculate and log decisions but do not gate.
3. Build a labeled evaluation set and calibrate thresholds against human review.
4. Measure added p50/p95 latency, tokens, cost, and failure rate.
5. Enable PDF gating for a small percentage of traffic.
6. Review false-pass and false-reject cases.
7. Enable fail-closed gating after thresholds are validated.

Shadow-mode evaluator output must never be presented as an authoritative quality
guarantee.

## Acceptance Criteria

The feature is complete when:

1. Every PDF-eligible diagnosis is evaluated before artifact creation.
2. Artifact writer is unreachable for `REVIEW`, `REJECT`, or evaluator failure.
3. The five metrics are calculated deterministically from auditable evaluator
   findings.
4. `final_decision` is calculated by application policy, not trusted from the
   LLM.
5. CrewAI evaluator has no tools and performs exactly one bounded LLM call.
6. Upstream ReAct orchestration supplies exactly one memoized, validated
   diagnosis observation.
7. Images and raw invalid output remain redacted.
8. Unit, integration, Ruff, coverage, and live one-image/six-image tests pass.
9. Thresholds are calibrated in shadow mode before production fail-closed gating.
