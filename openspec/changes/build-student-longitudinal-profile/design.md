## Context

The runtime already creates a guardrail-approved structured diagnosis for each invocation and renders it as a Markdown report for the caller, PDF artifacts, and email delivery. That report is intentionally scoped to the current images and must not use previous invocations as evidence for the current question diagnosis.

The new use case is different: after successful single-attempt diagnoses have been saved as structured JSON reports and indexed by student/test metadata, a student or teacher can request a per-subject longitudinal report. The report should explain recurring learning gaps across multiple diagnosis reports, not re-diagnose individual images.

The primary stakeholders are:

- Student: needs clear study priorities and an explanation of repeated learning gaps.
- Teacher: needs intervention notes that explain what to reteach, drill, or monitor.

## Goals / Non-Goals

**Goals:**

- Associate successful diagnosis reports with a parsed student id, parsed student name, parsed test/paper name, parsed subject, and the existing recipient email.
- Persist report-level metadata with parsed student id, recipient email, student name, subject, test/paper name, diagnosis date, diagnosis report id, the S3 path of the structured JSON diagnosis report, optional PDF/Markdown artifact paths, and the number of questions analysed.
- Store structured JSON diagnosis report artifacts beside the PDF artifact in S3.
- Preserve structured diagnosis JSON reports as historical learning evidence.
- Generate a written, requested, per-subject longitudinal profile report.
- Use a separate profile analysis agent for longitudinal reports.
- Use semantic analysis to cluster same or related concept gaps and wrong approaches across reports.
- Treat every diagnosed wrong-question item as a mistake for profile purposes.
- Mark an exact gap or broader related pattern as recurring only when supported by at least two separate diagnosis reports.
- Include both student-facing priorities and teacher-facing intervention notes.
- Keep major insights traceable to source diagnosis evidence.

**Non-Goals:**

- Automatic profile generation after every diagnosis.
- Cross-subject profile synthesis.
- Time-window based reports such as last 7 days or last 30 days.
- A visual graph UI in this change; the first output is a written report.
- Changing the evidence rules for the current single-attempt diagnosis workflow.
- Parsing PDF or Markdown reports as the source of profile evidence.

## Decisions

### Parse Student Metadata From S3 Prefix

Diagnosis invocations will not add new request fields for student/test metadata. For S3-backed requests, the runtime will parse student id, student name, test/paper name, and subject from the existing `image_s3_prefix` path when it follows the canonical layout:

```text
users/{student_id}/{student_name}/tests/{test_name}/subjects/{subject}/questions/
users/{student_id}/{student_name}/tests/{test_name}/subjects/{subject}/questions/{question_file}
```

For example, `users/YWuzXTHQ/Mock_Student/tests/MINOR_TEST_2_Paper_2/subjects/Physics/questions/Question_1.png` yields student id `YWuzXTHQ`, student name `Mock_Student`, test name `MINOR_TEST_2_Paper_2`, and subject `Physics`. The existing `recipient_email` remains the unique email identity for profile lookup. The parsed student id is stored as an internal reference, not the primary profile lookup key.

Rationale: the upstream image layout already carries the required student/test context, while email remains the stable unique lookup key for profile requests. Avoiding new payload fields keeps the request contract stable and avoids duplicating metadata that can drift from the S3 path.

Alternative considered: add explicit `student_email`, `student_name`, and `test_name` payload fields. Rejected because the user wants no request-side changes and the path already contains the authoritative non-email metadata.

### Keep Single-Attempt Diagnosis Separate From Profile Analysis

The existing diagnosis workflow remains evidence-grounded to the current images. Longitudinal analysis runs only over stored diagnosis evidence after the fact.

Rationale: the current prompt and guardrails intentionally prevent prior invocations from influencing diagnosis of the current images. Mixing prior profile context into the current diagnosis would weaken that guarantee and make unsupported conclusions more likely.

Alternative considered: feed student profile into every diagnosis. Rejected for this change because it changes the meaning of single-attempt diagnosis and needs separate safety evaluation.

### Store Report Metadata And Structured JSON Diagnosis Artifacts

Each successful diagnosis will write a structured JSON diagnosis report artifact and a report-level metadata record. The metadata record indexes parsed student id, recipient email, parsed student name, parsed subject, parsed test/paper name, diagnosis date, diagnosis report id, JSON report S3 path, optional PDF/Markdown artifact paths, and number of questions analysed. The JSON artifact contains question-level diagnosis rows including chapter, topic, likely thought, why wrong, exact concept gap, and deep-dive recommendation.

Rationale: reliable profile analysis requires machine-readable diagnosis evidence and a queryable index. Markdown and PDF are useful presentation formats but brittle for analytics.

Alternative considered: parse saved Markdown reports later. Rejected because it couples analytics to presentation formatting and loses structured validation guarantees.

### Store JSON Beside PDF Artifacts

For profile-capable S3 invocations, the structured JSON diagnosis artifact will be stored beside the PDF artifact, using the same basename with a `.json` suffix. The existing source prefix already includes student id, student name, test name, and subject path segments.

Example artifact layout:

```text
s3://bucket/users/{student_id}/{student_name}/tests/{test_name}/subjects/{subject}/questions/{subject}_analysis.pdf
s3://bucket/users/{student_id}/{student_name}/tests/{test_name}/subjects/{subject}/questions/{subject}_analysis.json
```

Rationale: the S3 layout should remain aligned with the incoming image organization, while the metadata table gives profile queries a compact index.

### Use Semantic Clustering Before Recurrence

The profile flow will first load the requested student's subject-scoped JSON reports, create compact evidence items, and run semantic gap analysis to identify same underlying gaps, same wrong approaches, same prerequisite weaknesses, same execution patterns, related-but-distinct subgaps, and unrelated mistakes. Recurrence is computed after clustering from distinct source diagnosis report ids.

Rationale: exact string matching is too weak because the same learning gap can appear with different wording. At the same time, report-count recurrence is a correctness rule and should not be left to prose generation.

Alternative considered: deterministic normalized-text grouping only. Rejected because it would miss subtle same-gap or same-approach patterns. Another alternative was to let the profile agent analyze raw reports end to end; rejected because it weakens evidence boundaries and makes recurrence claims harder to validate.

### Recurrence Is Report-Based

An exact gap or broader related pattern is recurring only when the accepted semantic cluster is supported by at least two separate diagnosis reports. Multiple questions in the same report may increase severity, but do not alone create recurrence.

Rationale: the product goal is long-term persistence across attempts. Report-level recurrence is a clearer functional signal than question count within one attempt.

Alternative considered: mark recurrence after two questions in any history. Rejected because it overclaims from a single session.

### Generate Profiles On Request

Profile reports will be generated only through an explicit profile request for a student email and subject.

Rationale: requested generation avoids unnecessary cost, avoids surprising users with automatic longitudinal claims, and keeps single-attempt diagnosis latency unchanged.

Alternative considered: automatically generate a fresh profile after every successful diagnosis. Rejected for this change because the user specifically wants requested generation.

### Use A Separate Profile Analysis Agent

The profile report will be generated by a separate profile analysis agent, not the existing CrewAI vision diagnosis agent. The profile agent receives a validated longitudinal evidence pack rather than images or raw unscoped report history.

Rationale: the profile agent has a different job: longitudinal synthesis from historical diagnosis evidence. It should not invoke vision tools, solve questions, or alter the current-attempt diagnosis flow.

Alternative considered: extend the existing diagnosis agent with profile context. Rejected because it risks mixing historical assumptions into current-attempt diagnosis and makes the agent harder to validate.

### Start With Written Reports

The first profile output is a written report with sections for overall summary, recurring gaps, chapter/topic weakness map, mistake pattern analysis, study priorities, teacher intervention notes, and evidence appendix.

Rationale: students and teachers need actionable interpretation before visual graphing. A written report is easier to validate for evidence grounding and usefulness.

Alternative considered: implement graph visualization first. Rejected because the graph is a supporting representation, not the core value.

## Risks / Trade-offs

- Semantic gap clustering may be noisy -> validate cluster evidence ids, separate exact recurring gaps from broader related patterns, and avoid declaring recurrence without two source reports.
- Low-history students may receive weak reports -> label one-report gaps as isolated or early indicators and avoid persistent-weakness language.
- Profile report may become generic -> require concrete affected chapters/topics, evidence counts, and specific study/intervention actions.
- Storing learning history introduces privacy obligations -> store recipient email only in the metadata email field, redact it from logs/prompts/telemetry, and never store image data URIs, base64 payloads, or full model internals in profile evidence.
- New storage access patterns differ from invocation status -> use a separate metadata store for student diagnosis report records and JSON artifact references instead of overloading invocation status records.
- LLM-generated profile prose can overclaim -> validate report structure and require evidence counts/references for major insights.

## Migration Plan

1. Add student/test metadata models and JSON diagnosis artifact models.
2. Add S3 prefix parsing for student id, student name, subject, and test/paper metadata without adding new request fields.
3. Write structured JSON diagnosis reports and metadata records only after successful, guardrail-approved diagnosis.
4. Add the requested profile report use case and separate profile analysis agent over metadata-indexed JSON reports.
5. Add semantic cluster validation, recurrence computation, and report validation.
6. Add durable storage, S3 artifact configuration, and runtime permissions.
7. Roll back by disabling profile report generation and metadata/JSON report writes; normal diagnosis analysis remains compatible.

## Open Questions

- Should requested profile reports be exposed through a second AgentCore entrypoint in the same runtime or a separate profile-agent runtime?
- Should metadata storage also expose a secondary lookup by parsed student id for operational debugging?
- What exact structured output schema should the semantic clustering agent return for exact gaps versus broader related patterns?
