## Context

The profile task currently embeds subject, chapter, topic, diagnosis text, and remediation text into one vector. Within a normalized chapter family, it connects every pair above a cosine threshold and treats each connected component as a semantic candidate. This provides useful recall, but contextual wording can dominate similarity and single-link chaining can create broad candidates.

The existing Gemini conceptual-strand classifier remains the semantic authority. Deterministic code remains responsible for evidence scope, reference integrity, chapter-family boundaries, confidence, and recurrence across diagnosis reports.

## Goals / Non-Goals

**Goals:**

- Align embedding similarity with the student's underlying misconception.
- Reduce bridge-item chaining without treating embedding geometry as the final semantic decision.
- Make every retrieved relationship explicitly classified and auditable.
- Preserve the profile request/response contract and evidence-backed recurrence rules.
- Keep the implementation modular, deterministic, and independently testable.

**Non-Goals:**

- Replace Gemini with unsupervised clustering.
- Change report rendering, recurrence thresholds, or diagnosis storage.
- Add a pedagogical action-planning stage.
- Tune thresholds from production data as part of this change.

## Decisions

### Use a focused misconception embedding

The embedding input will include only:

- exact concept gap;
- likely student thought;
- why that thought is wrong.

Subject remains the profile scope, and normalized chapter family remains a deterministic retrieval boundary. Topic and deep-dive recommendation remain available to Gemini as classifier context.

The embedding input version will be incremented so existing cached vectors cannot be mistaken for the new representation. The text hash remains a second stale-cache safeguard.

Alternative considered: weighted multi-vector embeddings. Rejected for this iteration because it adds storage, model calls, and uncalibrated weights before a labelled evaluation set exists.

### Retrieve mutual top-k neighbor pairs

Within each chapter family, deterministic retrieval will calculate pairwise cosine similarity and rank each item's neighbors by descending similarity with a stable evidence-ID tie-breaker. A candidate pair is retained only when:

- its cosine similarity meets the absolute floor; and
- each item is within the other item's top-k neighbors.

The initial defaults remain configurable in code: cosine floor `0.68` and `k=3`.

The result is an explicit list of immutable candidate pairs containing pair ID, evidence IDs, chapter family, similarity, and reciprocal ranks.

Alternative considered: DBSCAN/HDBSCAN. Rejected because per-student chapter-family histories can be small, a valid recurring gap may contain only two reports, and density-based output would incorrectly act as the final semantic cluster rather than high-recall retrieval.

Alternative considered: average-link clustering. Deferred until a labelled cluster benchmark is available; mutual pairs provide a smaller change and a clearer audit boundary.

### Make Gemini classify every candidate relationship explicitly

The conceptual-strand response will contain one relationship decision for every retrieved pair. The allowed labels are:

- `same_underlying_gap`;
- `related_but_distinct`;
- `unrelated`;
- `non_conceptual`.

Each decision includes the candidate pair ID and rationale. Gemini may still synthesize strands and exclusions in the same structured response, but deterministic validation will require:

- exact coverage of retrieved pair IDs;
- no invented or duplicate pair decisions;
- every multi-evidence strand to be connected by `same_underlying_gap` relationships;
- no retrieved pair inside a strand to be explicitly labelled with a conflicting relationship.

This keeps one semantic model call while making the reasoning boundary observable and enforceable.

Alternative considered: one LLM call for pair classification and a second for strand synthesis. Deferred because it doubles semantic-call latency and cost. The single-call schema plus deterministic consistency checks provides the required contract.

### Isolate retrieval primitives from legacy semantic clustering

Mutual-neighbor retrieval and its data model will live in a dedicated profile clustering module. The conceptual-strand pipeline will not depend on the older connected-component candidate builder. The older semantic module remains available for broader-pattern candidate construction until separately retired.

## Risks / Trade-offs

- [Risk] Mutual top-k retrieval can miss a real relationship when an item has many close neighbors. → Keep an absolute threshold plus configurable `k`, and add labelled retrieval evaluation before production tuning.
- [Risk] A low-data chapter family may behave like threshold retrieval because all neighbors fit inside top-k. → Gemini remains the final classifier and deterministic consistency validation remains mandatory.
- [Risk] Gemini may omit or contradict a relationship decision. → Strict schema and exact deterministic relationship validation fail closed instead of accepting an unsupported strand.
- [Risk] Focused embeddings may lose disambiguating topic context. → Topic and recommendation remain in the Gemini evidence payload, while chapter family remains a retrieval boundary.
- [Trade-off] Pair-level relationship output increases response size. → Mutual retrieval limits the number of pairs, and the added auditability justifies the bounded schema expansion.

## Migration Plan

1. Introduce focused embedding text with new cache input versions.
2. Add the mutual-neighbor retrieval module and unit tests.
3. Extend the conceptual classifier schema and prompt with explicit relationship decisions.
4. Enforce relationship coverage and strand consistency in deterministic validation.
5. Run profile regression tests, the complete unit suite, branch coverage, lint, and CD smoke/eval gates.
6. Roll back by reverting the change; stored diagnosis evidence and previously cached embedding records remain compatible because cache keys are versioned.

## Open Questions

- The best cosine floor and neighbor count require a labelled diagnosis-pair dataset. Defaults in this change preserve the current floor and use a conservative `k=3`.
