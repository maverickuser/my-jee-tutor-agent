## Context

The current profile flow embeds all question diagnoses for a subject, creates global similarity connected components, asks one LLM to classify flat clusters, and asks a second LLM to rewrite those clusters into a multi-section report. This allows related but distinct concepts to be presented as one recurring gap and gives broader patterns no independent analytical stage.

The replacement can be breaking because there are no current profile-report clients. Existing diagnosis JSON, metadata lookup, embedding infrastructure, invocation entrypoint, artifact storage, and Markdown-to-PDF generation remain reusable.

## Goals / Non-Goals

**Goals:**

- Identify recurring concept gaps within a canonical chapter/topic from at least two diagnosis reports.
- Synthesize broader conceptual-reasoning patterns only from validated local recurring gaps in different chapter/topic contexts.
- Preserve structured evidence, misconception, correction, confidence, counts, actions, and component relationships.
- Render only Overall Summary, Recurring Gaps, Broader Related Patterns, and Evidence Appendix.
- Use the real test date when available and explicitly mark it unavailable otherwise.
- Keep generative analysis to one local-classification call and one conditional broader-pattern call; render deterministically.

**Non-Goals:**

- Cross-subject synthesis.
- Time-trend inference beyond distinguishing test date from diagnosis date.
- Reporting isolated, execution-only, arithmetic, or prompt-reading patterns as conceptual findings.
- Preserving the legacy profile-report JSON schema.

## Decisions

### Use two-stage analysis

Stage 1 groups evidence by canonical chapter/topic, proposes local candidates with existing embeddings, and classifies exact recurring concept gaps. Stage 2 embeds the validated local-gap summaries and classifies cross-context broader patterns. This mirrors the report semantics and prevents raw question similarity from directly becoming a subject-level claim.

Alternative: strengthen the existing one-stage prompt. Rejected because a flat cluster cannot represent both local exactness and a hierarchy of broader component gaps reliably.

### Normalize taxonomy before local clustering

Use normalized case/spacing aliases over the existing chapter/topic strings and preserve canonical display values. Evidence with unknown taxonomy remains usable locally under its normalized label, but a broader pattern requires distinct normalized contexts. This change will not add a new external taxonomy service.

Alternative: require exact raw strings. Rejected because the current reports already demonstrate naming drift.

### Replace generic clusters with purpose-specific structured models

Local gaps include required concept, shared misconception, corrective concept, confidence, rationale, evidence IDs, and canonical location. Broader patterns include shared reasoning gap, common corrective principle, component local-gap IDs, manifestations, confidence, and rationale.

Alternative: retain title/type/rationale only. Rejected because exactness and hierarchy would remain unauditable.

### Keep recurrence deterministic

A local gap is report-recurring only when its evidence spans at least two diagnosis report IDs. A broader pattern must reference at least two recurring local gaps from distinct canonical contexts. Counts are always recomputed from source evidence.

### Use deterministic report construction

Classifier outputs include enough structured meaning for rendering. The report builder deterministically selects up to two priority local gaps and one broader pattern for the summary and embeds concise student/teacher actions in finding entries.

Alternative: retain the final report LLM. Rejected because it can re-merge findings and spends a model call reinterpreting validated structures.

### Add optional test date without mislabelling diagnosis date

Add nullable `test_date` to diagnosis metadata and evidence. Existing records deserialize with no test date. The appendix displays the real date when present; otherwise it explicitly says unavailable and may separately display the diagnosis date.

### Replace the report schema directly

There are no clients, so remove legacy fields instead of versioning or maintaining compatibility shims.

## Risks / Trade-offs

- Strict local clustering may reduce recall → keep embedding candidate recall broad and allow the classifier to merge equivalent wording within a context.
- Similarity connected-component chaining may still over-group locally → constrain candidates by context and require a same-concept/same-correction classifier proof.
- Broader-pattern synthesis may overgeneralize → require component recurring-gap IDs from distinct contexts and reject low-confidence outputs.
- Existing records lack test dates → render an explicit unavailable label and keep diagnosis date distinct.
- A subject may have too much evidence for one classifier call → batch by deterministic context groups while preserving one logical analysis stage.
- Model failure may leave no conceptual report → fail safely or render validated stages only; never fall back to heuristic broad claims.

## Migration Plan

1. Add nullable test-date fields and backward-compatible metadata deserialization.
2. Add local and broader structured analysis models and classifiers.
3. Replace the evidence pack and application orchestration with the two-stage flow.
4. Replace the report schema, deterministic builder, validator, and renderer.
5. Update unit, application, artifact, smoke, and quality tests.
6. Deploy as a direct schema replacement because there are no clients.
7. Roll back by reverting the runtime commit; stored diagnosis metadata remains readable because the new field is nullable.

## Open Questions

- A future source of authoritative test dates may require invocation or assessment-catalog integration; the first implementation accepts the field when supplied and otherwise marks it unavailable.
