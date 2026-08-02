## Why

The profile pipeline currently embeds contextual and recommendation text together with the diagnosed misconception, then uses threshold-connected components that can join distinct gaps through a bridge item. Candidate formation should focus on the student's incorrect mental model and provide explicit, auditable semantic relationships before conceptual strands are accepted.

## What Changes

- Build profile evidence embeddings from the exact concept gap, likely student thought, and explanation of why that thought is wrong.
- Keep subject and chapter family as deterministic scope controls rather than embedding features.
- Replace unrestricted similarity connected components with mutual top-k neighbor retrieval plus an absolute cosine-similarity floor.
- Require the semantic classifier to label candidate relationships as the same underlying gap, related but distinct, unrelated, or non-conceptual.
- Form conceptual-strand candidates only from relationships classified as the same underlying gap.
- Preserve deterministic evidence repair, chapter-family validation, confidence requirements, and cross-report recurrence rules.
- Add regression tests for bridge-item chaining, one-sided neighbors, explicit relationship labels, and focused embedding inputs.

## Capabilities

### New Capabilities

- `profile-semantic-candidate-clustering`: Defines focused misconception embeddings, mutual-neighbor candidate retrieval, explicit semantic relationship adjudication, and evidence-backed strand formation.

### Modified Capabilities

None.

## Impact

- Affects profile embedding input construction and cache input versioning.
- Refactors semantic candidate generation and conceptual-strand classifier schemas.
- Updates profile clustering prompts, validation, and profile unit/integration tests.
- Does not change the profile task request or response contract, report sections, recurrence threshold, diagnosis workflow, or stored diagnosis artifacts.
