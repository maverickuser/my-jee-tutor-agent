# Curriculum Taxonomy Generation

The runtime curriculum validator consumes an approved JSON taxonomy artifact. It
must not parse syllabus PDFs during normal tutor invocations.

Use `scripts/build_curriculum_taxonomy.py` as the explicit generation entry
point. The job requires:

```text
CURRICULUM_SOURCE_PDF_S3_URIS=s3://bucket/path/math.pdf,s3://bucket/path/physics.pdf,s3://bucket/path/chemistry.pdf
CURRICULUM_TAXONOMY_OUTPUT_S3_URI=s3://agent-bucket/curriculum/jee_curriculum_taxonomy.json
CURRICULUM_TAXONOMY_VERSION=2026-01
PUBLISH_TAXONOMY=false
```

Default behavior writes a pipeline artifact only. It does not publish to the
approved runtime S3 URI unless `PUBLISH_TAXONOMY=true`.

Before approving publish:

1. Confirm all source PDFs are explicit and readable.
2. Review the generated JSON artifact.
3. Confirm schema validation and deterministic sanity checks passed.
4. Review the diff against the current approved taxonomy when one exists.
5. Re-run with `PUBLISH_TAXONOMY=true` only after approval.

Runtime deployment should receive only:

```text
CURRICULUM_TAXONOMY_S3_URI=s3://agent-bucket/curriculum/jee_curriculum_taxonomy.json
CURRICULUM_TAXONOMY_REQUIRED=true
```

Local development may omit taxonomy config or set
`CURRICULUM_TAXONOMY_REQUIRED=false` to fail open.
