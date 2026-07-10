# Curriculum Taxonomy Generation

The runtime curriculum validator consumes an approved JSON taxonomy artifact. It
must not parse syllabus PDFs during normal tutor invocations.

The approved taxonomy is maintained locally at:

```text
knowledge/jee_curriculum_taxonomy.json
```

The CD workflow validates that file and uploads it to the stable runtime S3 URI
only when the remote object is missing or the local version/checksum changed.
The default runtime URI is:

```text
s3://web-scraper-dev-055173110395-ap-south-1-screenshots/curriculum/jee_curriculum_taxonomy.json
```

Override the destination with the GitHub Actions variable:

```text
CURRICULUM_TAXONOMY_S3_URI=s3://bucket/curriculum/jee_curriculum_taxonomy.json
```

Before changing the local taxonomy:

1. Extract or review the source syllabus PDFs locally.
2. Update `knowledge/jee_curriculum_taxonomy.json`.
3. Increment the JSON `version` when the approved taxonomy meaning changes.
4. Run schema validation and tests.
5. Let CD upload the stable runtime object if the version/checksum changed.

The older `scripts/build_curriculum_taxonomy.py` helper remains available for
controlled experiments, but CD uses `scripts/publish_curriculum_taxonomy.py` as
the approved local-file publisher.

Runtime deployment should receive only:

```text
CURRICULUM_TAXONOMY_S3_URI=s3://web-scraper-dev-055173110395-ap-south-1-screenshots/curriculum/jee_curriculum_taxonomy.json
CURRICULUM_TAXONOMY_REQUIRED=true
```

Local development may omit taxonomy config or set
`CURRICULUM_TAXONOMY_REQUIRED=false` to fail open.
