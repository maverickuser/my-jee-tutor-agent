## ADDED Requirements

### Requirement: Focused misconception embedding
The profile system SHALL embed the diagnosed misconception rather than contextual or remediation metadata.

#### Scenario: Question evidence is embedded
- **WHEN** the system creates an embedding for question-level profile evidence
- **THEN** the embedding input SHALL contain the exact concept gap, likely student thought, and explanation of why that thought is wrong
- **AND** the embedding input SHALL NOT contain subject, chapter, topic, or deep-dive recommendation text

#### Scenario: Focused representation replaces an earlier cached representation
- **WHEN** focused misconception embeddings are introduced
- **THEN** the embedding input version SHALL change
- **AND** an embedding created from the previous representation SHALL NOT be reused as the current representation

### Requirement: Deterministically scoped mutual-neighbor retrieval
The profile system SHALL retrieve candidate evidence relationships within deterministic subject and chapter-family boundaries using mutual top-k neighbors and an absolute cosine-similarity floor.

#### Scenario: Reciprocal neighbors meet the similarity floor
- **WHEN** two evidence items are in the same chapter family
- **AND** each item is within the other item's top-k neighbors
- **AND** their cosine similarity meets the configured floor
- **THEN** the system SHALL emit one candidate relationship containing both evidence IDs, their reciprocal ranks, similarity, and chapter family

#### Scenario: Neighbor relationship is one-sided
- **WHEN** one evidence item is within another item's top-k neighbors but the relationship is not reciprocal
- **THEN** the system SHALL NOT emit that candidate relationship

#### Scenario: Similarity is below the absolute floor
- **WHEN** two evidence items are reciprocal neighbors but their similarity is below the configured floor
- **THEN** the system SHALL NOT emit that candidate relationship

#### Scenario: Evidence belongs to different chapter families
- **WHEN** two evidence items belong to different normalized chapter families
- **THEN** the system SHALL NOT compare them as local conceptual-strand neighbors

#### Scenario: Similarities are tied
- **WHEN** multiple neighbors have equal cosine similarity
- **THEN** the system SHALL use a stable evidence-ID ordering to determine neighbor ranks

### Requirement: Explicit semantic relationship classification
The conceptual-strand classifier SHALL explicitly classify every retrieved candidate relationship before its evidence can support a conceptual strand.

#### Scenario: Candidate relationships are classified
- **WHEN** candidate relationships are sent to the conceptual-strand classifier
- **THEN** the classifier SHALL return exactly one decision for every candidate pair
- **AND** every decision SHALL use one of `same_underlying_gap`, `related_but_distinct`, `unrelated`, or `non_conceptual`
- **AND** every decision SHALL include an evidence-grounded rationale

#### Scenario: Classifier invents or duplicates a candidate pair
- **WHEN** classifier output references an unknown candidate pair or classifies one pair more than once
- **THEN** deterministic validation SHALL reject the unsupported relationship output

#### Scenario: Classifier omits a candidate pair
- **WHEN** classifier output does not classify every retrieved candidate pair
- **THEN** deterministic validation SHALL reject the incomplete relationship output

### Requirement: Same-gap relationships constrain conceptual strands
The system SHALL accept a multi-question conceptual strand only when its membership is supported consistently by explicit same-underlying-gap relationship decisions.

#### Scenario: Strand evidence is connected by same-gap relationships
- **WHEN** every evidence item in a proposed strand is connected to the strand through relationships classified as `same_underlying_gap`
- **AND** no retrieved relationship internal to the strand has a conflicting classification
- **THEN** the strand SHALL be eligible for existing evidence, confidence, and recurrence validation

#### Scenario: Proposed strand contains unsupported membership
- **WHEN** a proposed multi-question strand is not connected by `same_underlying_gap` relationships
- **THEN** deterministic validation SHALL reject the strand

#### Scenario: Internal relationship contradicts strand membership
- **WHEN** two evidence items in one proposed strand have a retrieved relationship classified as related but distinct, unrelated, or non-conceptual
- **THEN** deterministic validation SHALL reject the strand

### Requirement: Existing recurrence and evidence safeguards remain authoritative
The clustering change SHALL preserve existing deterministic conceptual-strand safeguards.

#### Scenario: Same-gap evidence occurs in one diagnosis report
- **WHEN** a valid conceptual strand is supported by multiple questions from only one diagnosis report
- **THEN** the system SHALL NOT report it as longitudinally recurring

#### Scenario: Same-gap evidence spans independent reports
- **WHEN** a valid medium- or high-confidence conceptual strand is supported by at least two diagnosis reports
- **THEN** the system SHALL remain eligible to report it as a recurring gap
