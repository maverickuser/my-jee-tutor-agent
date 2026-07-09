# Deterministic Curriculum Validator Spec

Status: Draft

Related documents:

- [`crewai-task-guardrail-spec.md`](crewai-task-guardrail-spec.md)
- [`crewai-controlled-react-orchestration-spec.md`](crewai-controlled-react-orchestration-spec.md)
- [`structured-output-spec.md`](structured-output-spec.md)

## Purpose

Validate the `chapter` and `topic` fields in the structured diagnosis output
against an approved JEE curriculum taxonomy using deterministic application
code.

This validation is deterministic code. It is not an LLM judge and it is not a
CrewAI Knowledge retrieval result.

The deterministic curriculum validator answers:

```text
Are the model-produced chapter/topic labels valid curriculum labels?
```

## Decision

Use a normalized taxonomy artifact as the runtime source of truth.

Do not validate chapter/topic directly from PDF text at request time.

Reason:

- PDF parsing and retrieval are not deterministic enough for a hard validator.
- Runtime validation should be fast, cheap, and testable.
- The diagnosis task guardrail already owns final task-output correctness.
- A taxonomy artifact can be versioned, cached, and audited.

## Source Inputs

The runtime curriculum source can come from either:

```text
1. Local files
2. S3 paths
```

Preferred production setup:

```text
s3://<bucket>/<prefix>/jee_curriculum_taxonomy.json
```

Optional source PDFs may also live in S3:

```text
s3://<bucket>/<prefix>/jee_syllabus_math.pdf
s3://<bucket>/<prefix>/jee_syllabus_physics.pdf
s3://<bucket>/<prefix>/jee_syllabus_chemistry.pdf
```

However, PDFs should be treated as upstream source material. The runtime
validator should consume the derived JSON taxonomy, not parse PDFs during every
agent invocation.

## Taxonomy Generation CD Job

Taxonomy JSON creation should be a separate, explicitly triggered CD job. It
must not run as part of every application deployment.

The job consumes syllabus PDFs and writes an approved taxonomy JSON artifact to
the agent bucket. The application then uses that S3 JSON path for guardrail
validation.

Inputs:

```text
CURRICULUM_SOURCE_PDF_S3_URIS=s3://bucket/path/math.pdf,s3://bucket/path/physics.pdf,s3://bucket/path/chemistry.pdf
CURRICULUM_TAXONOMY_OUTPUT_S3_URI=s3://agent-bucket/curriculum/jee_curriculum_taxonomy.json
CURRICULUM_TAXONOMY_VERSION=2026-01
PUBLISH_TAXONOMY=false
```

Required job behavior:

1. Download the explicitly supplied source PDFs.
2. Extract candidate subject/chapter/topic labels into a draft taxonomy JSON.
3. Validate the draft against the taxonomy schema.
4. Run deterministic taxonomy sanity checks.
5. Produce a diff against the currently approved taxonomy, if one exists.
6. Store the generated JSON as a pipeline artifact.
7. Publish to `CURRICULUM_TAXONOMY_OUTPUT_S3_URI` only when explicitly approved.

The job may use document parsing and LLM-assisted extraction to create a draft,
but the generated artifact is not approved until it passes schema validation and
review. Runtime validation must only consume the approved JSON artifact.

The published artifact should include provenance metadata:

```json
{
  "version": "2026-01",
  "source_documents": [
    {
      "subject": "Mathematics",
      "uri": "s3://bucket/path/math.pdf",
      "etag": "..."
    }
  ],
  "generated_at": "2026-07-09T00:00:00Z",
  "approved_at": "2026-07-09T00:00:00Z",
  "subjects": {}
}
```

Application deployment should receive only the approved taxonomy JSON path:

```text
CURRICULUM_TAXONOMY_S3_URI=s3://agent-bucket/curriculum/jee_curriculum_taxonomy.json
```

## Why Not Direct PDF Validation

CrewAI Knowledge supports PDF knowledge sources, but that is RAG context for an
agent. It must not be used as the authoritative validation mechanism.

PDF Knowledge can help the agent reason with curriculum references, but it
should not be the hard correctness gate for `chapter` and `topic`.

The hard correctness gate should be the deterministic curriculum validator,
which uses:

```text
normalized diagnosis JSON
approved taxonomy JSON
deterministic matching code
```

## Taxonomy Artifact

Suggested JSON shape:

```json
{
  "version": "2026-01",
  "source_documents": [],
  "generated_at": "2026-07-09T00:00:00Z",
  "approved_at": "2026-07-09T00:00:00Z",
  "subjects": {
    "Mathematics": {
      "chapters": {
        "Calculus": {
          "aliases": ["Differential Calculus", "Integral Calculus"],
          "topics": {
            "Limits": {
              "aliases": ["Limit of a Function"]
            },
            "Continuity": {
              "aliases": []
            }
          }
        }
      }
    },
    "Physics": {
      "chapters": {}
    },
    "Chemistry": {
      "chapters": {}
    }
  }
}
```

Minimum required fields:

- `version`
- `source_documents`
- `subjects`
- `chapters`
- `topics`
- optional `aliases`

## S3 Support

Runtime config should support:

```text
CURRICULUM_TAXONOMY_S3_URI=s3://bucket/path/jee_curriculum_taxonomy.json
CURRICULUM_TAXONOMY_LOCAL_PATH=knowledge/jee_curriculum_taxonomy.json
CURRICULUM_TAXONOMY_CACHE_TTL_SECONDS=3600
CURRICULUM_TAXONOMY_REQUIRED=true
```

Resolution order:

```text
1. If CURRICULUM_TAXONOMY_S3_URI is set, load taxonomy from S3.
2. Else if CURRICULUM_TAXONOMY_LOCAL_PATH is set, load local taxonomy.
3. Else taxonomy validation is disabled or fails closed based on
   `CURRICULUM_TAXONOMY_REQUIRED`.
```

Recommended default:

```text
fail_closed = true in production
fail_closed = false in local development
```

S3 loading should happen outside the CrewAI agent. The agent should not receive
AWS permissions or perform S3 reads.

## Cache Policy

The taxonomy loader should cache the parsed taxonomy in process memory.

Cache key:

```text
taxonomy source URI + ETag/version
```

Required behavior:

- avoid S3 reads on every invocation,
- refresh after TTL,
- reload when S3 ETag changes,
- fail closed if taxonomy is required and cannot be loaded,
- log taxonomy version and source, not full contents.

TTL behavior:

```text
before TTL expiry: use cached parsed taxonomy without an S3 read
after TTL expiry: issue S3 HeadObject
if ETag changed: fetch, parse, validate, and swap cache atomically
if ETag unchanged: extend cache TTL
```

For local files, use file mtime plus content hash to detect changes after TTL.

## Deterministic Validator Behavior

For each diagnosis item:

```text
chapter = diagnosis.chapter
topic = diagnosis.topic
```

Validate:

1. `chapter` matches an approved chapter or chapter alias.
2. `topic` matches an approved topic or topic alias under the resolved chapter.
3. If subject is later added to schema, validate subject/chapter/topic hierarchy.

The current diagnosis schema does not include `subject`, so initial validation
must search across all subjects unless subject can be inferred safely elsewhere.

If a chapter name exists in multiple subjects, the taxonomy should either:

- resolve it only if exactly one subject/chapter/topic path matches after
  normalization and alias expansion, or
- fail with `ambiguous_chapter_topic`.

Sentinel values:

```text
Unable to determine from image
```

If both `chapter` and `topic` use this sentinel, taxonomy validation should pass
for that diagnosis item and emit a separate low-confidence observation metric.
If only one field uses the sentinel, validation fails with
`partial_curriculum_label`.

## Normalization

Normalize labels before matching:

- trim whitespace,
- casefold,
- collapse repeated whitespace,
- remove non-semantic punctuation,
- normalize common symbols such as `&` to `and`,
- support explicit aliases from taxonomy.

Do not use fuzzy matching by default.

Fuzzy matching may be added later only if:

- it is deterministic,
- threshold is configured,
- false positives are tested,
- accepted fuzzy matches are logged as such.

## Guardrail Integration

Add this validation inside the deterministic CrewAI task guardrail after:

```text
JSON parsing
schema validation
expected image/question shape validation
```

Guardrail sequence becomes:

```text
1. Output exists
2. Vision tool observation exists
3. Output is JSON
4. Tool observation is valid
5. Final output matches valid tool observation
6. Schema is valid
7. Image/question shape is valid
8. Chapter/topic taxonomy is valid
```

Failure category:

```text
curriculum_taxonomy_mismatch
```

More specific categories:

```text
unknown_chapter
unknown_topic
topic_not_in_chapter
ambiguous_chapter_topic
partial_curriculum_label
taxonomy_unavailable
taxonomy_invalid
```

The guardrail must validate structured JSON output. If markdown output remains
supported, it must first be parsed into the same diagnosis model before
curriculum validation. Markdown must not bypass the deterministic curriculum
validator.

## Retry Policy

Taxonomy mismatch means the tool observation itself is invalid for the
curriculum contract.

Therefore it belongs to:

```text
semantic vision retry with cache invalidation
```

Behavior:

```text
first observation is marked rejected
CrewAI receives guardrail feedback
if retry budget remains, the vision tool may execute once more
second observation must pass taxonomy validation
if it fails again, workflow fails
```

Example feedback:

```text
VALIDATION_ERROR: unknown_topic.
  The diagnosis topic must match the approved JEE curriculum taxonomy.
  Re-run the vision analyzer once and choose chapter/topic labels from the approved taxonomy.
```

Do not include the full taxonomy in the feedback message.

The current workflow allows only one successful vision tool execution. To
support taxonomy retries, the implementation must add an explicit
taxonomy-retry path that:

1. marks the first observation rejected,
2. invalidates the cached tool observation for this invocation,
3. permits exactly one additional vision tool execution,
4. preserves the existing single-success invariant for all non-retry paths.

## Failure Scenarios and Edge Cases

Taxonomy generation job failures:

- source PDF URI is missing, malformed, or not readable,
- one or more expected subjects are absent from the generated draft,
- PDF extraction produces empty chapters or topics,
- generated JSON fails schema validation,
- generated taxonomy removes many existing labels unexpectedly,
- output S3 write fails,
- publish is attempted without explicit approval.

Runtime loader failures:

- taxonomy S3 URI is missing while `CURRICULUM_TAXONOMY_REQUIRED=true`,
- S3 object does not exist or access is denied,
- taxonomy JSON is malformed,
- taxonomy schema version is unsupported,
- taxonomy is valid JSON but semantically empty,
- cache reload fails after an older valid taxonomy is already cached.

Runtime loader behavior:

- if required and no valid cached taxonomy exists, fail closed with
  `taxonomy_unavailable` or `taxonomy_invalid`,
- if reload fails but a valid cached taxonomy exists, keep using the cached
  taxonomy and emit a reload failure metric,
- if fail-open local development mode is configured, skip curriculum validation
  and log that validation is disabled.

Validation edge cases:

- labels differ only by case, whitespace, or non-semantic punctuation,
- alias collides with a canonical label in another subject,
- one chapter alias maps to multiple canonical chapters,
- one topic alias maps to multiple topics under the same chapter,
- topic is approved but under a different chapter,
- chapter is approved but topic is unknown,
- subject is unavailable in the diagnosis schema,
- diagnosis contains the allowed sentinel for both chapter and topic,
- diagnosis contains the sentinel for only one of chapter/topic,
- multiple images produce mixed valid and invalid diagnosis items.

Each failure should return a compact category and human-readable guardrail
feedback. Do not include the full taxonomy, source PDF content, or S3 object
metadata beyond version/source identifiers in feedback.

## Optional CrewAI Knowledge Usage

CrewAI PDF Knowledge can still be added as context, but it is optional.

Possible use:

```text
Attach curriculum PDFs as CrewAI knowledge_sources so the orchestration agent
has curriculum context.
```

But the deterministic taxonomy validator remains authoritative.

If CrewAI Knowledge is used with S3 PDFs, the runtime should first materialize
the PDFs to local files because CrewAI `PDFKnowledgeSource` expects file paths.
This materialization should happen in infrastructure/application code, not in
the agent.

## Proposed Modules

Add:

```text
scripts/build_curriculum_taxonomy.py
src/jee_tutor/curriculum/taxonomy.py
src/jee_tutor/curriculum/loader.py
src/jee_tutor/curriculum/validator.py
```

Responsibilities:

```text
taxonomy.py
  Pydantic models for taxonomy artifact

build_curriculum_taxonomy.py
  explicit CD/manual job entry point for generating draft taxonomy JSON from
  supplied PDF locations

loader.py
  local/S3 taxonomy loading, caching, ETag/version handling

validator.py
  deterministic chapter/topic validation and normalization
```

## Metrics

Emit:

```text
curriculum_taxonomy_loaded_count
curriculum_taxonomy_load_failed_count
curriculum_taxonomy_version
curriculum_taxonomy_source
curriculum_taxonomy_validation_pass_count
curriculum_taxonomy_validation_fail_count
curriculum_taxonomy_failure_category_count
curriculum_taxonomy_semantic_retry_count
curriculum_taxonomy_generation_started_count
curriculum_taxonomy_generation_failed_count
curriculum_taxonomy_generation_published_count
```

Do not log full taxonomy content.

## Tests

Required tests:

1. Valid chapter/topic passes.
2. Chapter alias passes.
3. Topic alias passes.
4. Unknown chapter fails.
5. Unknown topic fails.
6. Topic under wrong chapter fails.
7. Ambiguous chapter/topic resolves only when exactly one taxonomy path matches;
   otherwise it fails.
8. Missing taxonomy fails closed when configured.
9. Missing taxonomy allows validation when fail-open local mode is configured.
10. S3 taxonomy loader uses cached taxonomy before TTL expiry.
11. S3 taxonomy loader reloads when ETag changes.
12. Taxonomy mismatch maps to semantic vision retry.
13. Second taxonomy mismatch fails workflow.
14. Taxonomy generation job fails when source PDFs are missing.
15. Taxonomy generation job validates output schema before publish.
16. Taxonomy generation job does not publish unless explicitly approved.
17. Markdown output cannot bypass curriculum validation.
18. Cached taxonomy remains in use when reload fails after a prior valid load.

## Acceptance Criteria

Implementation is complete when:

1. Runtime can load approved taxonomy from S3 or local file.
2. Chapter/topic validation is deterministic and does not call an LLM.
3. Task guardrail validates chapter/topic against taxonomy.
4. Taxonomy mismatch triggers semantic vision retry with cache invalidation.
5. A second taxonomy mismatch fails the workflow.
6. CrewAI Knowledge PDFs, if used, are optional context and not the validator.
7. Separate CD job can generate a draft taxonomy from explicitly supplied PDF
   S3 locations.
8. CD job publishes taxonomy JSON to the agent bucket only when explicitly
   approved.
9. Application runtime consumes only the approved taxonomy JSON S3 path.
10. Metrics prove taxonomy generation, validation pass/failure, cache, and retry
    behavior.
