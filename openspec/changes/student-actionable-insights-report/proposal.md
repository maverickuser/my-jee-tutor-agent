## Why

The current profile task summarizes longitudinal concept gaps but does not consistently turn repeated mistakes into concise preventive advice a student can use on the next question. The existing structured diagnosis JSON in S3 and cached question embeddings in DynamoDB provide a stronger input path for a replacement profile task that produces specific, evidence-backed actions rather than long or abstract diagnoses.

## What Changes

- Add a subject-wise analysis method that finds the first reasoning divergence for each wrong question and classifies the failure.
- **BREAKING** Replace the current profile task response and synthesis behavior while retaining its task name, supported aliases, student/subject lookup contract, and no-image invocation path.
- Load structured diagnosis JSON from its recorded S3 URI as the authoritative evidence source.
- Reuse matching question embeddings from the `jee-tutor-agent-evidence-embeddings` DynamoDB table for candidate-pattern discovery, creating only missing or stale embeddings through the existing embedding service.
- Require embedding and JSON linkage through `diagnosis_json_s3_uri`, `evidence_id`, embedding model, and embedding input version.
- Use embedding similarity only to propose candidate groups; validate shared behavior and preventive action against structured JSON before emitting an insight.
- Aggregate only genuinely similar failures across questions using shared reasoning behavior and a shared corrective action, rather than shared chapter labels alone.
- Preserve question-level concept gaps as evidence while producing a small number of prioritized cross-question insights.
- Translate each recurring pattern into a short trigger-and-action instruction that a student can apply proactively.
- Define a compact student report in language suitable for a 16-year-old: a memorable self-question, one immediate `Do` instruction, and an `Ask this when you see` cue tied to visible question features.
- Retain evidence references and confidence in internal output metadata rather than displaying uncertainty disclaimers in the default student report.
- Render the student-facing actionable-insights report as a PDF and upload it to `s3://jee-tutor-agent-terraform-state/profile-reports/<student-name>+<student-id>/<subject_name>/<subject_name>_profile_report.pdf`.
- Return the uploaded PDF URI in the successful profile-task response and treat PDF rendering or upload failure as a profile artifact failure.

## Capabilities

### New Capabilities
- `student-actionable-insights`: Analyze subject-wise wrong-question reports and generate concise, specific, proactive student guidance supported by question-level evidence.

### Modified Capabilities

- `tutor-invocation`: Route the existing profile task and aliases to the replacement actionable-insights behavior without requiring image input.

## Impact

- Replaces the current profile service output and synthesis behavior behind the existing profile task contract.
- Reuses the existing diagnosis metadata store, S3 structured-diagnosis artifact store, evidence embedding service, and DynamoDB embedding table.
- Adds PDF rendering and S3 upload to the replacement profile-task success path using the fixed `jee-tutor-agent-terraform-state` bucket and `profile-reports/` prefix.
- Adds a structured intermediate representation for question failures, candidate clusters, validated recurring insights, internal evidence/confidence, and student actions.
- Requires migration of profile reporting tests and consumers to the compact actionable-insights response.
- Does not change diagnosis artifact creation, PDF rendering, or diagnosis delivery behavior.
