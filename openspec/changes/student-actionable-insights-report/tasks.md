## 1. Structured Evidence and Models

- [x] 1.1 Add validated models for question failure classification, evidence provenance/confidence, candidate groups, recurring insights, student action, and usage trigger.
- [x] 1.2 Extend the existing profile evidence loader to expose the structured diagnosis fields and stable report/question identities required by actionable synthesis.
- [x] 1.3 Add handling for missing, malformed, or inaccessible diagnosis JSON that records an internal loading error without falling back to PDF or Markdown parsing.

## 2. Embedding-Assisted Candidate Discovery

- [x] 2.1 Reuse the existing evidence embedding service to retrieve compatible DynamoDB records by S3 URI and complete embedding key and to regenerate missing or stale vectors.
- [x] 2.2 Implement candidate-group discovery from compatible embeddings without scanning the embedding table for student or subject records.
- [x] 2.3 Add validation that accepts a candidate group only when its structured JSON evidence shares a comparable failure stage, observable behavior, and one preventive action.

## 3. Actionable-Insight Synthesis

- [x] 3.1 Implement first-divergence classification for concept-not-applied, incorrectly applied, incompletely applied, execution, attention, and strategy/representation failures.
- [x] 3.2 Preserve distinct question-level concept gaps when different concepts are grouped under one shared preventive behavior.
- [x] 3.3 Rank validated patterns by independent recurrence, likely mark impact, and internal confidence, returning at most three insights.
- [x] 3.4 Keep single-question failures as internal question-level feedback and prevent them from being labeled recurring insights.
- [x] 3.5 Load versioned chapter-weightage JSON from S3 and list at most five repeated-mistake chapters in combined-weightage order.

## 4. Profile Task Replacement

- [x] 4.1 Replace the existing profile service synthesis and renderer with actionable-insight generation while retaining `profile` and all supported task aliases.
- [x] 4.2 Render each student-visible insight as a self-question heading plus `Do` and subject-specific `Ask this when you see`, and omit evidence codes, internal labels, and inference disclaimers.
- [x] 4.3 Return internal structured metadata containing supporting questions, question-level gaps, provenance, and confidence for audit and ranking.
- [x] 4.4 Preserve the existing no-image profile invocation path, student/subject lookup, and successful no-history behavior.
- [x] 4.5 Remove or bypass the previous longitudinal profile synthesis and report renderer from the active profile composition path.
- [x] 4.6 Add deterministic sanitization and URI construction for `s3://jee-tutor-agent-terraform-state/profile-reports/<student-name>+<student-id>/<subject_name>/<subject_name>_profile_report.pdf`.
- [x] 4.7 Render the student-view model to PDF, upload it to the required URI, and return `profile_report_pdf_uri` only after successful upload.
- [x] 4.8 Add handled profile artifact failures for rendering, invalid path components, and S3 upload errors without exposing internal evidence.

## 5. Migration and Verification

- [x] 5.1 Update profile model and parsing tests for the replacement response, internal metadata, self-question/`Do`/`Ask this when you see` fields, and validation failures.
- [x] 5.2 Update evidence-loading and storage-adapter tests for structured JSON authority, exact JSON-to-embedding identity matching, cache reuse, stale embedding replacement, malformed JSON, inaccessible S3 objects, and no DynamoDB scan behavior.
- [x] 5.3 Update clustering, semantic-pack, and hierarchical-profile tests so embedding similarity only proposes candidates and structured JSON validation decides whether an actionable insight is supported.
- [x] 5.4 Add actionable-profile service tests for the three-insight limit, age-appropriate language, visible question cues, prospective wording, internal evidence retention, and absence of evidence codes or inference disclaimers in student output.
- [x] 5.5 Update application-profile, task-router, invocation-handler, and alias tests to prove every existing profile task name reaches the replacement flow while diagnosis routing remains unchanged.
- [x] 5.6 Update profile artifact tests for PDF-only student-view content, exact S3 URI, deterministic path sanitization, successful upload response, rendering/upload failure, and exclusion of internal metadata.
- [x] 5.7 Add versioned Maths, Physics, and Chemistry evaluation fixtures covering all 18 structured reports and 105 matching `manual` embeddings, including expected supported and rejected candidate groups.
- [x] 5.8 Add actionable-insight evaluation assertions for evidence grounding, shared-behavior validation, one preventive action per group, maximum three insights, age-appropriate wording, subject-specific cues, and no unsupported claims.
- [x] 5.9 Add or update the profile evaluation runner so it emits a machine-readable report and fails its gate when required actionable-insight assertions fail.
- [x] 5.10 Update `scripts/run_agentcore_profile_smoke.py` and `tests/pipeline_scripts/test_run_agentcore_profile_smoke.py` to assert the replacement response, non-empty `profile_report_pdf_uri`, exact key convention, and successful PDF artifact retrieval.
- [x] 5.11 Update CI/CD profile smoke and evaluation steps, artifact collection, deployment configuration, and `tests/deployment/test_terraform_cd_eval_access.py` for read access to diagnosis JSON/embeddings and write access to the fixed profile-report prefix.
- [x] 5.12 Add regression cases for no history, one-question history, no validated recurring pattern, missing/stale embeddings, malformed evidence, synthesis schema failure, and PDF failure.
- [ ] 5.13 Run the complete profile unit/integration suite, pipeline-script tests, actionable-insight evaluations, AgentCore profile smoke test, deployment tests, and project lint/coverage gates.
