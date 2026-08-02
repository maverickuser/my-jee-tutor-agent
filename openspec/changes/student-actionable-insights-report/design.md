## Context

The current profile task already loads student-and-subject diagnosis history, builds question evidence, creates or reuses embeddings, clusters evidence, and renders a longitudinal report. Its output emphasizes profile structure and concept-gap summaries rather than a small set of preventive actions.

Each structured diagnosis JSON is stored in S3 and referenced by diagnosis metadata. Question embeddings are cached in the `jee-tutor-agent-evidence-embeddings` DynamoDB table under the composite key `diagnosis_json_s3_uri` plus `embedding_key`; the latter encodes evidence identity, embedding model, and input version. The replacement must reuse this path rather than scan DynamoDB or parse PDF/Markdown reports.

The synthesis must retain traceability to individual questions, distinguish observed work from inferred reasoning internally, avoid treating embedding proximity as proof, and prevent the student report from becoming another long revision list.

## Goals / Non-Goals

**Goals:**

- Define a repeatable question-to-pattern analysis pipeline.
- Replace the existing profile task behavior behind its current task name and aliases.
- Treat structured diagnosis JSON as authoritative evidence and embeddings as candidate-discovery aids.
- Produce at most three prioritized, evidence-backed student insights by default.
- Make each insight a concrete trigger-and-action instruction.
- Preserve question references, provenance, and confidence internally without exposing analytical disclaimers to the student.
- Persist every successful student-facing report as a PDF at the required S3 profile-report location.
- Support any subject, with subject-specific triggers supplied by the input evidence.

**Non-Goals:**

- Replacing question-level concept-gap analysis.
- Inferring the student's actual reasoning with certainty when written working is unavailable.
- Producing a full revision syllabus, detailed lesson plan, or generic motivational feedback.
- Grouping errors solely by chapter, topic, or similar answer values.
- Discovering student evidence by scanning the embedding table.
- Using embedding similarity as sufficient evidence for a recurring insight.

## Decisions

### Replace profile behavior without changing invocation identity

The existing `profile` task and supported aliases remain the external entry point. The task continues to require student identity and subject while requiring no diagnosis image source. Its handler is replaced or re-composed to run actionable-insight synthesis and return the compact report plus optional internal evidence metadata.

Introducing a second parallel task was rejected because this capability is intended to supersede, not coexist with, the current student profile output.

### Load JSON before using embeddings

The existing diagnosis metadata query determines which reports belong to the requested student and subject. For each metadata record, the system loads the structured diagnosis JSON from `diagnosis_json_s3_uri` and creates ordered question evidence with identifiers of the form `<diagnosis_report_id>:q<ordinal>`.

The embedding table is a cache, not the source of report discovery. Scanning for an `embedding_key` prefix such as `manual` was rejected because the table keys support direct lookup by S3 URI and complete embedding key, not efficient student/subject discovery.

### Use embeddings for candidate discovery only

The existing embedding service retrieves a cached vector when model, input version, and text hash match, and regenerates missing or stale vectors. Similarity search proposes candidate question groups. The structured JSON fields—especially exact concept gap, likely thought, and why wrong—then determine whether candidates share an observable failure and one preventive action.

This separation prevents same-topic questions with different failure behaviors from being incorrectly merged.

### Use a two-level representation

Each wrong question is first represented as a `QuestionFailure`, containing question reference, first divergence, required concept or rule, application status, failure behavior, S3/report provenance, embedding identity, evidence, and confidence. Similarity produces candidate groups. Validated recurring failures are then represented as an `Insight`, containing supporting question references, shared behavior, student trigger, preventive action, priority, and confidence.

This keeps the question-level diagnosis intact while allowing cross-question synthesis. A single free-form summary was rejected because it makes evidence, confidence, and grouping decisions difficult to verify.

### Detect the first meaningful divergence

Analysis starts at the earliest step where the described solution differs from the correct solution. The divergence is classified as concept not applied, incorrectly applied, incompletely applied, execution error, attention error, or strategy/representation gap.

Using the final wrong answer alone was rejected because different reasoning paths can produce the same answer and lead to different interventions.

### Group by shared behavior and shared prevention

Two failures may join the same recurring insight only when they share:

1. a comparable stage of failure,
2. the same observable reasoning behavior, and
3. a single preventive action that applies naturally to both.

Shared chapter or topic labels are insufficient. For example, a wrong Taylor coefficient and a missed algebraic factor both occur in limits but require different prevention. Conversely, a missed modulus branch and a missed negative quadratic branch may share the preventive prompt “Could there be another case?” even though their question-level concepts remain distinct.

### Separate diagnostic labels from student language

Internal labels such as “incomplete solution-space coverage” are used for aggregation but are not emitted as the primary advice. The student receives a short instruction such as: “When you see modulus, a square, a root, or a piecewise rule, pause and ask: Could there be another case?”

This translation is required because abstract diagnostic terminology is not directly actionable.

### Use separate student and internal output contracts

The default student report contains no more than three insights. Each insight has exactly three student-visible parts:

- **Self-question heading:** a short question the student can mentally ask during an exam, such as “Could there be another case?”;
- **Do:** one immediate, observable preventive behavior;
- **Ask this when you see:** recognizable subject-specific visual or wording cues in the question.

The heading must not use analytical labels such as “incomplete solution-space coverage” or formal teacher language such as “verify exhaustive case enumeration.” The `Do` instruction uses direct verbs and describes a small action that can be performed in rough work. The usage cue names things the student can actually notice, such as modulus signs, piecewise definitions, switches, reaction conditions, or words like “incorrect.”

Evidence references, internal pattern labels, source confidence, and reasoning provenance remain available as internal structured metadata. The student report does not include “reasoning is inferred” or similar analytical disclaimers. It also avoids definitive claims about an unobserved thought process by phrasing guidance prospectively.

### Render and persist the student report as PDF

After synthesis and schema validation, the student-visible content is rendered to PDF and uploaded to:

`s3://jee-tutor-agent-terraform-state/profile-reports/<student-name>+<student-id>/<subject_name>/<subject_name>_profile_report.pdf`

`<student-name>`, `<student-id>`, and `<subject_name>` are sanitized as individual path components using a deterministic allowlist of letters, numbers, dot, underscore, and hyphen; unsafe runs are replaced with underscores and leading or trailing punctuation is removed. The plus sign between the sanitized student name and ID is a literal separator. The subject component used for the directory and filename is identical.

The PDF contains only the student-facing self-question, `Do`, and `Ask this when you see` content plus minimal report identity such as student and subject. Internal evidence, confidence, source URIs, and diagnostic labels are excluded. A profile-task response is successful only after upload succeeds and includes the resulting S3 URI.

### Rank by recurrence, impact, and confidence

Priority is determined by recurrence across independent questions and reports, likely mark impact, and confidence in the evidence. Patterns supported by one question remain question-level feedback and are not presented as recurring insights. Confidence affects internal ranking and metadata, not the default student wording.

## Migration Plan

1. Add the actionable-insight models and synthesis behind the existing profile application boundary.
2. Reuse the current metadata loader, S3 diagnosis artifact store, embedding service, and embedding cache.
3. Replace the current profile renderer and response fields with the compact actionable-insights response while retaining task names and aliases.
4. Add student-only PDF rendering and upload to the required profile-report S3 key and return its URI.
5. Update profile unit, integration, smoke, evaluation, artifact, IAM, and end-to-end coverage to the replacement contract.
6. Gate deployment on deterministic contract checks plus fixture-based Maths, Physics, and Chemistry actionable-insight evaluations.
7. Deploy without changing the diagnosis workflow or stored diagnosis/embedding formats.
8. Roll back by restoring the previous profile service composition and renderer; stored JSON and embeddings remain compatible.

## Risks / Trade-offs

- **Over-grouping distinct concepts** → Require shared behavior and shared prevention, and retain the narrower question-level gaps as evidence.
- **Embedding proximity mistaken for proof** → Treat vectors as candidate discovery only and validate with structured JSON.
- **Overconfident diagnosis from generated reports** → Carry confidence internally and phrase student advice prospectively.
- **Advice becomes generic or age-inappropriate** → Require a memorable self-question, one direct `Do` instruction, and visible `Ask this when you see` cues suitable for a 16-year-old.
- **Report becomes too long** → Default to three insights and one action per insight.
- **Low-frequency but important gaps disappear** → Preserve them in question-level feedback even when they do not qualify as recurring insights.
- **Existing profile consumers expect old fields** → Treat the output replacement as a migration, update consumers and tests, and keep rollback at the composition boundary.
- **PDF target bucket or permissions are unavailable** → Fail the profile artifact step with a concise handled error and do not claim successful report delivery.
- **Internal evidence leaks into the PDF** → Render from a dedicated student-view model that excludes internal metadata by construction.
