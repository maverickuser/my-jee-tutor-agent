## 1. Guardrail Foundations

- [x] 1.1 Add `src/jee_tutor/agent/task_guardrails.py` with output extraction, canonical JSON normalization, safe error summaries, and retry category models.
- [x] 1.2 Implement `build_diagnosis_task_guardrail(...)` using invocation-scoped `VisionToolCallState`, expected image count, expected question numbers, and optional taxonomy validator.
- [x] 1.3 Validate empty output, missing tool observation, non-JSON output, canonical mismatch, structured schema errors, question-count mismatch, question-number mismatch, and duplicate readable question numbers.
- [x] 1.4 Emit safe task guardrail telemetry for every guardrail check without logging full output, invalid output, image payloads, or recipient email.
- [x] 1.5 Add unit tests for all task guardrail pass/fail and retry-category paths.

## 2. Vision Tool State and Controlled Retry

- [x] 2.1 Extend `VisionToolCallState` with observation validation, rejection category, semantic retry count, semantic retry budget, cached replay count, and observation replacement fields.
- [x] 2.2 Add helper methods to mark observations valid, reject observations, determine whether cached replay is allowed, and determine whether a fresh semantic retry execution is allowed.
- [x] 2.3 Update `VisionAnalysisTool` duplicate-call behavior so valid observations replay, rejected observations do not replay, cached failures still fail, and semantic retry can execute once.
- [x] 2.4 Enforce real vision execution count <= 2 per invocation and emit budget-exhausted telemetry.
- [x] 2.5 Add tests for cached finalization retry, rejected-observation retry, observation replacement, retry exhaustion, and execution-count caps.

## 3. CrewAI Task and Workflow Wiring

- [x] 3.1 Update diagnosis task construction to attach the deterministic guardrail and set `max_retries=1`.
- [x] 3.2 Pass expected image count, expected question numbers, invocation id, and status-store context through crew/task factories as needed.
- [x] 3.3 Determine and configure the smallest CrewAI orchestration call budget that supports forced first tool action, final answer, and one guardrail retry.
- [x] 3.4 Update the CrewAI/ReAct workflow so post-workflow code consumes guardrail-approved JSON for deterministic Markdown rendering without duplicating the same correctness checks.
- [x] 3.5 Ensure task guardrail failure prevents Bedrock output guardrail, artifact creation, email delivery, and success response formatting.
- [x] 3.6 Add workflow tests for valid no-retry path, malformed finalization retry, semantic retry, missing observation, tool failure, exhausted retry, and artifact/response safety boundaries.

## 4. CrewAI Hooks

- [x] 4.1 Add `src/jee_tutor/agent/crew_callbacks.py` with `CrewCallbackContext`, `CrewCallbacks`, and `build_crew_callbacks(...)`.
- [x] 4.2 Implement before-kickoff callback logging safe start metadata and optional status-store event writes.
- [x] 4.3 Implement after-kickoff callback logging safe completion metadata, tool counters, task guardrail metadata when available, and optional status-store event writes.
- [x] 4.4 Implement task callback logging task metadata, elapsed time when available, output length, and guardrail pass/fail metadata without full output.
- [x] 4.5 Wire before-kickoff, after-kickoff, and task callbacks into `build_tutor_crew(...)`; keep `step_callback` unwired.
- [x] 4.6 Add tests for callback bundle construction, crew wiring, hook failure policy, and privacy-safe logs.

## 5. Curriculum Taxonomy Runtime

- [x] 5.1 Add `src/jee_tutor/curriculum/taxonomy.py` with Pydantic models for version, source documents, subjects, chapters, topics, and aliases.
- [x] 5.2 Add `src/jee_tutor/curriculum/loader.py` supporting S3 and local taxonomy sources, required/fail-open configuration, cache TTL, S3 ETag refresh, local mtime/hash refresh, and atomic cache replacement.
- [x] 5.3 Add `src/jee_tutor/curriculum/validator.py` with deterministic normalization, canonical/alias matching, ambiguity detection, sentinel handling, and failure categories.
- [x] 5.4 Integrate taxonomy validation into the diagnosis task guardrail after JSON/schema/image/question checks.
- [x] 5.5 Map taxonomy mismatches to semantic vision retry with rejected-observation cache invalidation.
- [x] 5.6 Add tests for taxonomy schema parsing, canonical matches, aliases, unknown labels, wrong chapter/topic pairings, ambiguity, sentinel behavior, missing taxonomy fail-closed, disabled taxonomy fail-open, cache TTL, ETag reload, and reload failure with valid cache.

## 6. Taxonomy Publish Job

- [x] 6.1 Add approved local `knowledge/jee_curriculum_taxonomy.json` with versioned Physics, Chemistry, and Mathematics taxonomy.
- [x] 6.2 Add `scripts/publish_curriculum_taxonomy.py` to validate the local JSON and upload the stable S3 object only when version or checksum changes.
- [x] 6.3 Add a separate CD job that publishes the taxonomy before AgentCore runtime deployment and stores a publish report as an artifact.
- [x] 6.4 Wire AgentCore runtime configuration and IAM so the deployed agent loads the same stable taxonomy S3 URI with fail-closed validation.
- [x] 6.5 Add tests proving missing remote upload, unchanged remote skip, changed remote upload, CD wiring, runtime env injection, and S3 read access.

## 7. Status, Metrics, and Privacy

- [x] 7.1 Extend invocation status telemetry for CrewAI kickoff, task completion, task guardrail checks, retry category, semantic retry, cached replay, observation rejection, and observation replacement.
- [x] 7.2 Extend nested LLM-call records or safe supplemental telemetry for batch size, attempt count, model/provider, success/failure, duration, optional token counts, and safe response summary.
- [x] 7.3 Add artifact safety and response safety counters proving artifacts and successful responses only occur after task guardrail approval.
- [x] 7.4 Add privacy tests ensuring status/log telemetry does not persist image data URIs, base64 payloads, full model responses, full invalid outputs, stack traces, or raw sensitive guardrail matches.

## 8. CI/CD Quality Gates

- [x] 8.1 Update CI test grouping or coverage to include controlled ReAct, task guardrail, hooks, taxonomy runtime, and taxonomy generation tests.
- [x] 8.2 Update eval or smoke reporting to include aggregate controlled ReAct, guardrail pass/fail, retry category, vision execution cap, taxonomy validation, and artifact safety evidence.
- [x] 8.3 Update CD taxonomy publish workflow to upload the approved local taxonomy JSON only when changed and inject the same stable S3 URI into runtime.
- [x] 8.4 Update Langfuse aggregate publishing to include safe guardrail/retry/taxonomy metrics when credentials are configured.
- [x] 8.5 Run `openspec validate implement-controlled-crewai-diagnosis`, unit tests, Ruff, and coverage before marking implementation complete.
