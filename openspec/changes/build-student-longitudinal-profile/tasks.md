## 1. Diagnosis Metadata And Artifact Models

- [x] 1.1 Add models for student diagnosis metadata with parsed student id, recipient email, parsed student name, parsed subject, parsed test or paper name, diagnosis report id, diagnosis date, structured JSON report S3 path, optional PDF/Markdown artifact paths, and number of questions analysed.
- [x] 1.2 Add models for structured JSON diagnosis report artifacts containing question-level diagnosis evidence.
- [x] 1.3 Add validation helpers for parsed student id, recipient email, subject, test or paper name, diagnosis report id, diagnosis date, and S3 artifact paths.
- [x] 1.4 Add privacy helpers to normalize/redact recipient email and parsed student metadata in traces, logs, prompts, and operational telemetry.

## 2. Diagnosis Invocation Capture

- [x] 2.1 Add parsing for student id, student name, test name, and subject from `image_s3_prefix` paths shaped as `users/{student_id}/{student_name}/tests/{test_name}/subjects/{subject}/questions/...`.
- [x] 2.2 Ensure safe trace input omits image payloads, recipient email, and parsed student metadata.
- [x] 2.3 Preserve or expose the guardrail-approved structured diagnosis response from the workflow for JSON artifact writing.
- [x] 2.4 Write the structured diagnosis JSON report artifact beside the PDF artifact after successful guardrail-approved diagnosis, preserving parsed student id, student name, test name, and subject path segments.
- [x] 2.5 Write the student diagnosis metadata record after the JSON report artifact is available, including parsed student id, recipient email, parsed student name, parsed test name, parsed subject, JSON artifact path, PDF artifact path when available, and number of questions analysed.
- [x] 2.6 Ensure validation failures, guardrail blocks, workflow failures, or unsuccessful responses do not write metadata or publish JSON reports as profile evidence.
- [x] 2.7 Include diagnosis report id and JSON report artifact metadata in successful responses when configured without breaking existing analysis fields.

## 3. Metadata And Artifact Storage

- [x] 3.1 Define a student diagnosis metadata port that can store records and query by recipient email plus subject, while retaining parsed student id as an internal reference field.
- [x] 3.2 Define a structured diagnosis artifact port that can write and load JSON diagnosis reports by S3 URI or configured artifact location.
- [x] 3.3 Add in-memory metadata and artifact stores for unit tests.
- [x] 3.4 Add durable metadata storage adapter and JSON artifact storage adapter.
- [x] 3.5 Add runtime configuration for metadata storage, JSON report artifact location, and failure policy.

## 4. Profile Evidence Loading

- [x] 4.1 Add a profile report request model requiring student email and subject.
- [x] 4.2 Load report metadata for the requested student and subject only.
- [x] 4.3 Load structured JSON diagnosis reports referenced by metadata records.
- [x] 4.4 Create compact evidence items with evidence id, diagnosis report id, question number, chapter, topic, likely thought, why wrong, exact concept gap, and deep-dive recommendation.
- [x] 4.5 Return a handled no-history response when no metadata or JSON diagnosis evidence exists.
- [x] 4.6 Ensure profile evidence loading excludes image data URIs, base64 payloads, raw model request bodies, raw model responses, and stack traces, with recipient email limited to the metadata email field.

## 5. Semantic Gap Analysis

- [x] 5.1 Add a semantic clustering prompt/schema for same underlying concept gap, same wrong approach, same prerequisite weakness, same execution pattern, related-but-distinct subgaps, and unrelated mistakes.
- [x] 5.2 Add an evidence embedding model/configuration and embedding input builder over subject, chapter, topic, exact concept gap, likely thought, why wrong, and deep-dive recommendation.
- [x] 5.3 Add a dedicated embedding store keyed by structured JSON diagnosis report path, evidence id, embedding model, and embedding input version, with an embedding text hash for stale detection.
- [x] 5.4 Ensure profile generation creates embeddings only for evidence items missing a matching stored embedding.
- [x] 5.5 Compute cosine similarity over requested student-and-subject evidence embeddings and create candidate cluster groups.
- [x] 5.6 Implement the mandatory semantic clustering LLM classifier over candidate groups and compact evidence items.
- [x] 5.7 Validate cluster output for known evidence ids, requested subject scope, required fields, duplicate evidence conflicts, and invented evidence references.
- [x] 5.8 Compute distinct diagnosis report counts, question counts, exact recurring gaps, broader recurring patterns, and isolated or early-indicator gaps from validated clusters.
- [x] 5.9 Build a chapter/topic map that distinguishes exact recurring gaps, broader related recurring patterns, and isolated gaps.

## 6. Longitudinal Evidence Pack

- [x] 6.1 Build a longitudinal evidence pack with summary counts, validated clusters, recurrence labels, chapter/topic map, mistake pattern summary, and evidence index.
- [x] 6.2 Ensure recurrence requires at least two separate diagnosis reports and is not inferred from multiple questions in one report alone.
- [x] 6.3 Preserve evidence references from profile insights back to diagnosis report ids and question numbers.
- [x] 6.4 Add serialization tests for the evidence pack schema.

## 7. Profile Analysis Agent

- [x] 7.1 Add a profile analysis agent or service separate from the current-attempt diagnosis agent.
- [x] 7.2 Ensure the profile agent consumes only the longitudinal evidence pack and does not invoke vision diagnosis tools or re-diagnose images.
- [x] 7.3 Add a profile report output schema with overall summary, recurring gaps, broader related patterns, chapter/topic weakness map, isolated gaps, study priorities, teacher intervention notes, and evidence appendix.
- [x] 7.4 Implement profile report generation from the evidence pack.
- [x] 7.5 Validate generated profile reports for evidence references, recurrence claims, subject scope, required sections, and sensitive value leakage.
- [x] 7.6 Render the validated profile report as written Markdown and optionally persist profile report artifacts.

## 8. Endpoint And Composition

- [x] 8.1 Add a requested profile report endpoint or AgentCore entrypoint for student email plus subject.
- [x] 8.2 Wire composition for metadata store, JSON artifact store, evidence embedding store/model, mandatory semantic clustering classifier, and profile analysis agent.
- [x] 8.3 Add deployment configuration, IAM permissions, and outputs for metadata storage and JSON diagnosis report artifacts.
- [x] 8.5 Add deployment configuration, IAM permissions, and outputs for the evidence embedding table.
- [x] 8.4 Ensure profile report generation can be disabled without breaking current diagnosis invocations.

## 9. Tests And Validation

- [x] 9.1 Add unit tests for parsing student id, student name, test name, and subject from canonical S3 image prefixes and keys.
- [x] 9.2 Add tests for JSON diagnosis artifact writing beside the PDF path and metadata record creation after successful diagnosis.
- [x] 9.3 Add tests proving no metadata or profile JSON artifact is published on validation, guardrail, workflow, or output failures.
- [x] 9.4 Add tests for metadata query by recipient email plus subject and exclusion of other subjects/students.
- [x] 9.5 Add tests for compact evidence loading from JSON diagnosis reports.
- [x] 9.6 Add tests that profile generation reuses existing matching embeddings and creates only missing or stale evidence embeddings.
- [x] 9.7 Add tests for cosine-similarity candidate generation within requested student-and-subject scope.
- [x] 9.8 Add tests proving final semantic clusters come from the mandatory LLM classifier, not raw embedding-neighbor groups.
- [x] 9.9 Add tests for semantic cluster validation, including invented evidence ids, duplicate evidence conflicts, and related-but-distinct subgaps.
- [x] 9.10 Add tests for recurrence requiring at least two separate diagnosis reports.
- [x] 9.11 Add tests for one-report profile reports using early-indicator language without recurring claims.
- [x] 9.12 Add tests for written report sections, student study priorities, teacher intervention notes, and evidence appendix.
- [x] 9.13 Add tests that metadata, evidence packs, profile prompts, reports, and telemetry exclude image data URIs, base64 payloads, raw model responses, and stack traces, and keep recipient email limited to the metadata email field.
- [x] 9.14 Run `openspec validate build-student-longitudinal-profile`, unit tests, Ruff, and coverage before marking implementation complete.
