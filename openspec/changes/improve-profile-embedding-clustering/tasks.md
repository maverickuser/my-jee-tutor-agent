## 1. Focused Embedding Representation

- [x] 1.1 Restrict question evidence embedding text to exact concept gap, likely thought, and why-wrong explanation.
- [x] 1.2 Increment embedding input versions and update embedding cache regression tests.

## 2. Mutual-Neighbor Candidate Retrieval

- [x] 2.1 Add a dedicated clustering module with immutable candidate-pair models and deterministic mutual top-k retrieval.
- [x] 2.2 Replace conceptual-strand connected-component candidates with chapter-family-scoped mutual-neighbor pairs.
- [x] 2.3 Add tests for reciprocal ranks, absolute similarity floor, stable ties, one-sided neighbors, chapter boundaries, and bridge-item behavior.

## 3. Explicit Relationship Adjudication

- [x] 3.1 Extend the conceptual-strand classifier schema and prompt with explicit pair relationship labels and rationales.
- [x] 3.2 Add deterministic repair and validation for exact pair coverage, duplicate or invented relationships, same-gap connectivity, and contradictory internal relationships.
- [x] 3.3 Update conceptual-strand analyzer and classifier tests for the relationship-aware contract.

## 4. Verification and Delivery

- [x] 4.1 Run focused profile tests and resolve regressions.
- [x] 4.2 Run the full unit/integration suite with branch coverage and lint.
- [x] 4.3 Validate the OpenSpec change and confirm documentation matches implemented defaults.
- [ ] 4.4 Push the scoped implementation and monitor CD through successful completion.
