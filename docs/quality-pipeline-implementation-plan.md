# Diagnosis Quality Pipeline: 20-Task Implementation Plan

Status: Proposed

## Purpose

Decompose the structured diagnosis, constrained CrewAI ReAct orchestration,
final evaluator, PDF gate, and mandatory CD eval specifications into small,
dependency-ordered deliverables.

Source specifications:

- [`structured-output-spec.md`](structured-output-spec.md)
- [`crewai-react-diagnosis-spec.md`](crewai-react-diagnosis-spec.md)
- [`final-evaluator-spec.md`](final-evaluator-spec.md)
- [`cd-final-evaluator-evals-spec.md`](cd-final-evaluator-evals-spec.md)

Each task should be implemented as an independently reviewable pull request or a
similarly small change. A task is complete only when all listed success criteria
are satisfied.

## Model Allocation

The implementation uses distinct pinned models:

```text
Diagnosis and vision reasoning: gemini/gemini-2.5-pro
Final quality evaluation:       gemini/gemini-2.5-flash
```

The Flash evaluator classifies claims and produces structured findings. It does
not calculate authoritative aggregate scores or `final_decision`. Tasks 11 and
12 calculate those deterministically in application code.

Model names must be explicit configuration values and included in observability
and CD assertions.

## Global Definition of Done

Every task must:

- Preserve existing public behavior unless the task explicitly changes it.
- Add or update unit and integration tests.
- Pass Ruff and `git diff --check`.
- Preserve the configured branch-coverage threshold.
- Avoid logging image payloads, credentials, or unbounded model output.
- Document new configuration and operational behavior.
- Keep provider, CrewAI, workflow, and whole-invocation retry ownership explicit.
- Leave PDF generation unreachable after an unapproved or invalid diagnosis.

## Task 1: Define Structured Diagnosis Models

### Scope

- Add `QuestionDiagnosis`.
- Add `DiagnosisResponse`.
- Require all seven diagnosis fields.
- Forbid unknown fields.
- Strip whitespace and reject blank values.
- Include field descriptions used by Gemini's JSON schema.
- Preserve unreadable-image sentinel values.

### Dependencies

None.

### Success criteria

1. Valid one-question and multi-question JSON parses successfully.
2. Missing, extra, null, non-string, and blank fields are rejected.
3. `Unreadable from image` and `Unable to determine from image` are accepted.
4. Generated JSON schema includes all required fields and descriptions.
5. No production call path is changed yet.

## Task 2: Add Deterministic Markdown Rendering

### Scope

- Render `DiagnosisResponse` into the existing seven-column Markdown table.
- Preserve column and question order.
- Normalize newlines.
- Escape Markdown pipes and backslashes safely.
- Preserve inline mathematical notation.

### Dependencies

- Task 1.

### Success criteria

1. Renderer output passes the existing Markdown validator.
2. Exactly one physical row is emitted per diagnosis item.
3. Pipes, backslashes, and multiline values cannot corrupt table structure.
4. Existing PDF rendering accepts the generated Markdown.
5. Renderer adds no heading or text outside the table.

## Task 3: Request Gemini Structured Output

### Scope

- Add LiteLLM `response_format` using the Pydantic JSON schema.
- Pin diagnosis requests to `gemini/gemini-2.5-pro`.
- Enable it for verified Gemini models.
- Preserve `caching=false`, `num_retries=0`, and configured timeout.
- Add schema name and version to observability metadata.
- Keep a feature flag for the legacy Markdown response path during migration.

### Dependencies

- Task 1.

### Success criteria

1. Mocked completion receives the expected `response_format`.
2. Every diagnosis call uses `gemini/gemini-2.5-pro`.
3. A live one-image Gemini call returns JSON compatible with Task 1.
4. Unsupported providers fail configuration clearly or use an explicitly
   configured legacy path.
5. LiteLLM does not add an internal retry.
6. Images remain redacted from logs and Langfuse input.

## Task 4: Add Structured Semantic Validation

### Scope

- Parse Gemini JSON with Pydantic.
- Validate image/result count.
- Validate image order and expected question-number policy.
- Reject duplicate questions except allowed unreadable sentinels.
- Define safe structured-output error categories.

### Dependencies

- Tasks 1 and 3.

### Success criteria

1. Wrong count, order, duplicates, and mismatched numbers are rejected.
2. Validation errors contain safe categories and bounded details.
3. Raw invalid output is not logged or returned.
4. Semantic failure does not trigger an LLM retry.
5. Valid structured output reaches the Task 2 renderer.

## Task 5: Add Invocation-Scoped Vision Tool Memoization

### Scope

- Replace duplicate-call rejection with memoized success and failure.
- Track request count separately from real execution count.
- Keep memoized state scoped to one workflow.
- Make successful observations immutable.

### Dependencies

- Task 4 for the target structured observation.

### Success criteria

1. First tool request executes `VisionLLMClient` once.
2. Duplicate request after success returns the same observation.
3. Duplicate request after failure raises the cached failure.
4. Duplicate requests never increment real execution count.
5. Separate workflow instances never share observations or failures.

## Task 6: Make Tool Memoization Concurrency-Safe

### Scope

- Protect state transitions with a lock and condition/future.
- Handle duplicate requests while the first execution is running.
- Add a bounded waiter deadline.
- Prevent deadlocks and abandoned running state.

### Dependencies

- Task 5.

### Success criteria

1. Concurrent callers produce exactly one real tool execution.
2. All callers receive the same observation or cached failure.
3. A stuck first execution releases waiters through a bounded timeout.
4. Concurrency tests pass repeatedly without race failures.
5. Request, execution, and success counters remain internally consistent.

## Task 7: Restore Constrained CrewAI ReAct Diagnosis

### Scope

- Restore `Crew.kickoff()` behind a feature flag.
- Give the diagnosis agent exactly one tool.
- Disable delegation, memory, code execution, and CrewAI retries.
- Force the first action to the vision tool.
- Configure a low iteration limit and explicit orchestration-call budget.
- Keep the direct workflow available for rollback.

### Dependencies

- Tasks 3 through 6.

### Success criteria

1. A successful workflow has exactly one Crew kickoff.
2. CrewAI requests the vision tool before producing a final answer.
3. One workflow has exactly one real vision tool execution.
4. Duplicate CrewAI requests replay memoized output.
5. The orchestration-call budget terminates runaway behavior.
6. Feature flag can return traffic to the direct path without changing output.

## Task 8: Enforce Tool-Observation Preservation

### Scope

- Compare CrewAI final content with the memoized structured observation.
- Reject additions, removals, rewrites, and reordered questions.
- Add `CrewObservationMismatchError`.
- Ensure deterministic Markdown rendering remains outside CrewAI.

### Dependencies

- Task 7.

### Success criteria

1. Unchanged observation is accepted.
2. Added, removed, reordered, or rewritten content is rejected.
3. Mismatch does not call the final evaluator or artifact writer.
4. CrewAI is not asked to repair a mismatch automatically.
5. Match status is recorded without logging full raw content.

## Task 9: Harden ReAct Failure Handling and Observability

### Scope

- Separate orchestration, tool request, real execution, and transport-attempt
  counters.
- Cache terminal provider failures.
- Add bounded iteration and call-budget errors.
- Add operation-specific Langfuse spans and metrics.

### Dependencies

- Tasks 7 and 8.

### Success criteria

1. First timeout followed by success produces one tool execution and two
   transport attempts.
2. Exhausted transport attempts do not cause another tool execution.
3. Iteration exhaustion cannot reach evaluation or artifact generation.
4. Logs distinguish every call category unambiguously.
5. Image payloads and full invalid model output remain redacted.

## Task 10: Define Final-Evaluator Output Models

### Scope

- Add claim kind and status enums.
- Add claim, per-question, and evaluator-assessment Pydantic models.
- Require row and field references.
- Forbid unknown fields and unbounded issue lists.
- Generate the evaluator response schema.

### Dependencies

- Task 1.

### Success criteria

1. Valid evaluator findings parse.
2. Missing, extra, invalid-enum, and invalid-reference-shaped fields fail.
3. Evaluator output cannot provide authoritative aggregate metrics or decision.
4. Schema version is explicit.
5. Model schema is covered by snapshot or equivalent contract tests.

## Task 11: Implement Deterministic Metric Calculation

### Scope

Calculate:

- `groundedness_score`
- `unsupported_claim_rate`
- `contradiction_rate`
- `completeness_score`
- `inference_quality_score`

### Dependencies

- Task 10.

### Success criteria

1. Supported, unsupported, and contradicted claims use mutually exclusive
   counts.
2. Three claim rates sum to `1.0` within tolerance.
3. Completeness uses applicable items rather than a fixed denominator.
4. Inference quality averages only defined applicable criteria.
5. Zero denominators, NaN, infinity, and out-of-range values fail closed.
6. Rounding occurs only after calculation.

## Task 12: Implement Deterministic Decision Policy

### Scope

- Add configurable pass and review thresholds.
- Calculate `PASS`, `REVIEW`, or `REJECT` in application code.
- Add hard failures for critical contradictions and invalid findings.
- Report failed threshold names.

### Dependencies

- Task 11.

### Success criteria

1. Exact pass boundaries produce `PASS`.
2. Values below pass but within review thresholds produce `REVIEW`.
3. Values below review thresholds produce `REJECT`.
4. Any critical contradiction produces `REJECT`.
5. LLM-provided decision text cannot override application policy.
6. Threshold configuration is validated at startup.

## Task 13: Add Tool-Free CrewAI Final Evaluator

### Scope

- Build a separate CrewAI evaluator agent and task.
- Give it images and validated diagnosis.
- Give it no tools, delegation, memory, or code execution.
- Pin the evaluator model to `gemini/gemini-2.5-flash`.
- Use one bounded structured LLM call.
- Add evaluator-specific timeout and model configuration.

### Dependencies

- Tasks 10 through 12.
- Task 8 for validated upstream diagnosis.

### Success criteria

1. Evaluator has zero tools and performs exactly one evaluator call.
2. Every evaluator call uses `gemini/gemini-2.5-flash` with temperature zero.
3. It cannot invoke or repeat diagnosis.
4. Valid findings produce deterministic metrics and decision.
5. Invalid findings fail closed without retry.
6. Evaluator images and raw output remain redacted.

## Task 14: Add the PDF Quality Gate

### Scope

- Run final evaluation before `_success_response` or artifact creation.
- Permit artifact writer only for `PASS`.
- Block PDF and Markdown fallback for `REVIEW`, `REJECT`, or evaluator failure.
- Add a safe final-evaluation error contract.
- Publish a correlated Langfuse observation and available evaluator scores for
  every sampled attempt, including rejected and errored attempts.
- Attach bounded rejection diagnostics matching the safe error contract.

### Dependencies

- Task 13.

### Success criteria

1. `PASS` calls artifact writer exactly once.
2. `REVIEW` and `REJECT` call artifact writer zero times.
3. Evaluator timeout or invalid JSON calls artifact writer zero times.
4. Unapproved diagnosis is not returned as a successful response.
5. Error response contains bounded metrics and failed thresholds.
6. `PASS`, `REVIEW`, `REJECT`, timeout, invalid-output, and evaluator-error
   attempts remain visible in Langfuse with their available metrics.
7. Rejected and errored observations identify failed thresholds and safe issue
   summaries without images, prompts, raw completions, credentials, stack
   traces, or student personal information.

## Task 15: Add Deterministic Evaluator Sampling

### Scope

- Add configurable sample rate.
- Select by stable hash of idempotency key.
- Use a canonical request fingerprint when no key is supplied.
- Support shadow and gated modes.
- Force 100% evaluation in CD.

### Dependencies

- Task 14.

### Success criteria

1. Same logical request always receives the same sampling result.
2. Sampling result is stable across process restarts.
3. Sample rate boundaries `0.0` and `1.0` behave correctly.
4. Shadow mode records decisions without blocking artifacts.
5. Gated mode enforces Task 14 for sampled requests.
6. CD configuration overrides sampling to `1.0`.

## Task 16: Add Mandatory CrewAI ReAct CD Evals

### Scope

- Add `run_crewai_react_evals.py`.
- Implement all ten `REACT-*` cases.
- Report operation-specific counts.
- Publish one correlated Langfuse observation per case with the boolean case
  result, operation counters, and bounded failure diagnostics.
- Require all cases to pass.

### Dependencies

- Tasks 5 through 9.

### Success criteria

1. All ten ReAct cases exist and execute.
2. Any failed, errored, or skipped case exits nonzero.
3. No aggregate minimum score is accepted.
4. Duplicate, concurrent, failure, and state-isolation cases prove one real
   execution per workflow.
5. Reports contain no image payloads or raw completion content.
6. Every executed case is visible in Langfuse even when a later case fails or
   the runner exits nonzero.
7. Failed and errored case observations contain the same sanitized, bounded
   reason and failed assertions as the runner summary.

## Task 17: Add Mandatory Final-Evaluator CD Evals

### Scope

- Add `run_final_evaluator_evals.py`.
- Add versioned S3 images and predefined diagnoses.
- Implement all ten `EVAL-*` cases.
- Compare metric ranges and decisions.
- Publish a parent run trace and one correlated Langfuse observation per case.
- Publish the five evaluator metrics as numeric scores and the case assertion
  result as a separate boolean score.
- Attach bounded diagnostics for assertion failures, evaluator errors, and
  actual `REVIEW` or `REJECT` decisions.
- Require all cases to pass.

### Dependencies

- Tasks 10 through 15.

### Success criteria

1. All ten evaluator cases exist and execute.
2. Positive, unsupported, contradicted, incomplete, inference, unreadable, and
   prompt-injection behavior is covered.
3. Any failed, errored, or skipped case exits nonzero.
4. No `0.75` or other aggregate threshold can pass the job.
5. Negative cases cannot allow artifact generation.
6. Every evaluator generation reports model `gemini/gemini-2.5-flash`.
7. Every case observation records case ID, expected/actual decision, all five
   metrics, question counts, critical issue count, artifact permission, schema
   version, model, and latency when available.
8. An expected `REJECT` has a passing case score when all fixture assertions
   pass; evaluator decision and case assertion are not conflated.
9. Failed, errored, `REVIEW`, and `REJECT` observations contain sanitized,
   bounded debug fields matching the JSON report and console summary.
10. Case observations are emitted as results are finalized and flushed before
    the all-pass gate exits.

## Task 18: Add Deployed AgentCore Runtime Smoke Test

### Scope

- Export runtime ID or endpoint ARN from deployment.
- Invoke the deployed runtime rather than local handler code.
- Use unique idempotency key and eval artifact name.
- Verify response, metrics, ReAct counters, PDF, S3 state, and deployed SHA.
- Publish the smoke assertion result, applicable counters and evaluator metrics,
  and bounded failure diagnostics to its correlated Langfuse observation.

### Dependencies

- Tasks 14, 16, and 17.

### Success criteria

1. Smoke test invokes the newly deployed AgentCore runtime.
2. Successful response passes structured and evaluator thresholds.
3. ReAct reports one real vision execution.
4. PDF exists and was created by the current workflow run.
5. Repeated idempotent request causes no second artifact write.
6. Runtime traces show diagnosis on `gemini/gemini-2.5-pro`.
7. Runtime traces show final evaluation on `gemini/gemini-2.5-flash`.
8. Any smoke assertion fails CD.
9. A failed smoke run remains diagnosable in Langfuse without exposing image
   content, prompts, raw completions, credentials, or student data.

## Task 19: Forward Structured Application Logs to New Relic

### Scope

- Standardize runtime application logs as structured records with timestamp,
  severity, service, environment, deployed commit SHA, request correlation ID,
  workflow stage, terminal outcome, and safe error category.
- Add a bounded, non-blocking application log transport that batches structured
  records and sends them directly to the regional New Relic Log API. Do not use
  a CloudWatch Logs subscription or log-forwarding Lambda.
- Follow the web-scraper deployment pattern for secret handling:
  `NEW_RELIC_LICENSE_KEY` exists only as a GitHub Actions secret; CD creates or
  updates an AWS Secrets Manager secret and passes only its ARN to Terraform.
- Grant the AgentCore runtime role `secretsmanager:GetSecretValue` only for that
  secret. Pass `NEW_RELIC_LICENSE_KEY_SECRET_ARN`, `NEW_RELIC_REGION`, and the
  enablement flag to the runtime; resolve the ingest key at process startup
  with a bounded timeout, without logging it or storing it in Terraform state.
- Implement the New Relic handler as asynchronous and fail-open. The request
  thread may redact, serialize, and call `put_nowait` on a bounded queue only;
  it must never fetch secrets, perform DNS/TLS/HTTP work, wait for queue space,
  retry delivery, or flush batches.
- Run batching, HTTPS delivery, and retries in a dedicated background worker.
  Catch every transport and worker exception inside the logging subsystem so it
  cannot propagate into invocation, diagnosis, evaluation, or artifact code.
- Configure bounded batch size, queue capacity, send timeout, retry count, and
  shutdown flush timeout. If initialization or secret retrieval fails, disable
  New Relic delivery and continue with normal application logging. When the
  queue is full or delivery is exhausted, drop the New Relic copy, increment an
  internal delivery-failure counter, emit a rate-limited fallback warning, and
  continue serving the request.
- Correlate New Relic logs with the corresponding Langfuse trace and evaluation
  observation when correlation identifiers are available.
- Emit a synthetic deployment canary and verify that the New Relic ingest API
  accepts it. Document the NRQL query used to confirm that the canary is
  searchable; automated querying requires a separate least-privilege New Relic
  query key and account ID, not the ingest license key.
- Add dashboards or saved queries for invocation count, failures by stage and
  category, evaluator decisions, latency, dropped records, and delivery health.
- Add alarms for sustained delivery errors, queue saturation, dropped records,
  and missing production logs.
- Document retention, access control, ownership, troubleshooting, and the
  procedure for rotating the New Relic ingest license key.

Application request handling must not depend on New Relic availability. Delivery
failure is an observability incident and must remain visible in the normal
AgentCore/CloudWatch logs; CloudWatch is a fallback sink, not the New Relic
forwarding path. Delivery failure must not change an evaluator decision or
application response. Shutdown flushing is best-effort and bounded; the process
must not hang waiting for New Relic.

### Dependencies

- Tasks 9 and 18.

### Success criteria

1. Structured logs from the deployed AgentCore runtime are visible and
   searchable in New Relic with service, environment, commit SHA, severity, and
   correlation fields.
2. A CD canary proves direct application-to-New Relic ingest without a
   CloudWatch subscription or forwarding Lambda.
3. Runtime and evaluation failures can be correlated between New Relic logs and
   Langfuse without using student identity as a correlation key.
4. Logs contain no image payloads, prompts, raw model or evaluator completions,
   credentials, signed URLs, or student personal information.
5. Delivery errors, queue saturation, dropped records, and missing-log
   conditions are monitored and alertable while normal runtime logs remain
   available in CloudWatch.
6. `NEW_RELIC_LICENSE_KEY` comes from a GitHub Actions secret, is upserted into
   AWS Secrets Manager before Terraform apply, and is never passed to Terraform,
   runtime environment variables, command output, or logs as plaintext.
7. New Relic unavailability does not block or alter production requests.
8. Dashboard queries, retention, access, ownership, and operational runbooks are
   documented.
9. Unit tests cover redaction, batching, queue overflow, timeouts, retries,
   shutdown flush, disabled configuration, and secret-fetch failure.
10. Tests prove that the request thread performs no secret or network I/O,
    never waits for queue capacity, and receives no exception from the logging
    subsystem when initialization, serialization, worker, or delivery fails.
11. Load tests demonstrate that slow or unavailable New Relic ingestion does
    not materially increase invocation latency or reduce request throughput;
    dropped-log and delivery-failure counters expose any resulting loss.

## Task 20: Shadow Rollout and Threshold Calibration

### Scope

- Enable ReAct and evaluator shadow modes for limited traffic.
- Retain direct diagnosis and non-gated artifact behavior as rollback controls.
- Collect human-reviewed metric labels.
- Measure latency, cost, evaluator stability, and false decisions.

### Dependencies

- Tasks 15 through 19.

### Success criteria

1. Shadow execution cannot block or alter production responses.
2. No duplicate real vision execution is observed.
3. Metric distributions and evaluator decisions are visible by model/version.
4. Diagnosis and evaluator latency and cost are reported separately.
5. Human-reviewed calibration set is documented.
6. Flash evaluator false-pass and false-reject rates meet agreed operational
   targets.
7. End-to-end timeout budget is validated at p95 and p99.

## Task 21: Enable Production ReAct and PDF Gating

### Scope

- Enable constrained ReAct diagnosis.
- Enable calibrated evaluator sampling.
- Enable fail-closed PDF gating for sampled requests.
- Configure alarms and rollback controls.
- Make all CD gates mandatory.

### Dependencies

- Tasks 1 through 20.

### Success criteria

1. All mandatory CI, ReAct CD, evaluator CD, and runtime smoke jobs pass.
2. Production has no duplicate real vision execution per workflow.
3. Only `PASS` decisions produce artifacts for gated requests.
4. Production diagnosis uses `gemini/gemini-2.5-pro`.
5. Production final evaluation uses `gemini/gemini-2.5-flash`.
6. Timeout, error, latency, and cost stay within approved budgets.
7. Rollback to direct diagnosis and disabled gating is tested.
8. Configuration, runbooks, dashboards, and ownership are documented.

## Recommended Pull Request Sequence

```text
PR 1: Tasks 1-2
PR 2: Tasks 3-4
PR 3: Tasks 5-6
PR 4: Tasks 7-9
PR 5: Tasks 10-12
PR 6: Tasks 13-14
PR 7: Task 15
PR 8: Task 16
PR 9: Task 17
PR 10: Task 18
PR 11: Task 19
PR 12: Task 20
PR 13: Task 21
```

Tasks should not be merged out of dependency order unless their code remains
disabled and cannot affect production behavior.
