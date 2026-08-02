## ADDED Requirements

### Requirement: Longitudinal Profile Objective
The system SHALL produce a per-subject longitudinal profile that gives students and teachers objective, evidence-backed, actionable insights by identifying specific concept-level gaps that recur across diagnosis reports, locating those gaps within the relevant chapter and topic, distinguishing them from broader related learning patterns and non-conceptual mistake patterns, and deriving appropriate next actions.

#### Scenario: Profile communicates a recurring concept gap
- **WHEN** evidence from at least two distinct diagnosis reports supports the same underlying concept gap
- **THEN** the profile SHALL identify the precise concept gap and its affected chapter and topic
- **AND** the profile SHALL explain the evidence-backed reasoning for treating the gap as recurring
- **AND** the profile SHALL provide actionable direction for both the student and teacher

#### Scenario: Evidence supports only related subgaps
- **WHEN** evidence from multiple diagnosis reports supports related-but-distinct concept gaps
- **THEN** the profile SHALL preserve the individual concept gaps as distinct
- **AND** the profile SHALL describe their relationship only as a broader related pattern
- **AND** the profile SHALL NOT present the related subgaps as one exact recurring concept gap

#### Scenario: Recurrence and time trend are distinguished
- **WHEN** a cluster is supported by at least two distinct diagnosis reports
- **THEN** the profile MAY describe the cluster as recurring across reports
- **AND** the profile SHALL describe the cluster as persistent, improving, worsening, or resolved over time only when evidence from sufficiently distinct reporting dates supports that trend

### Requirement: Semantic Cluster Type Preservation
The system SHALL preserve the scope and type of each validated conceptual finding through local clustering, broader synthesis, evidence-pack construction, report generation, and report validation.

#### Scenario: Local recurring concept gap is routed
- **WHEN** a validated recurring concept gap describes the same or closely equivalent conceptual misunderstanding within one canonical chapter/topic context
- **THEN** it SHALL be eligible for the Recurring Gaps section
- **AND** its chapter/topic scope SHALL remain attached to the finding

#### Scenario: Cross-context conceptual pattern is routed
- **WHEN** validated local concept gaps from different chapter/topic contexts share the same type of conceptual reasoning failure
- **THEN** the synthesized finding SHALL be eligible for the Broader Related Patterns section
- **AND** the broader pattern SHALL reference its component local gaps
- **AND** it SHALL NOT replace or be duplicated as one local recurring gap

#### Scenario: Non-conceptual pattern is available
- **WHEN** evidence supports only a careless execution, arithmetic, prompt-reading, or generic study-behavior pattern without a conceptual relationship
- **THEN** the system SHALL NOT present it as a Recurring Gap or Broader Related Pattern

### Requirement: Constrained Semantic Classification
The system SHALL use semantic search only to propose potentially related diagnosis evidence and SHALL use a constrained semantic classifier to determine the supported relationship among the candidate evidence items.

#### Scenario: Semantic search proposes candidates
- **WHEN** embedding similarity or normalized semantic matching identifies potentially related diagnosis evidence
- **THEN** the system SHALL treat the resulting group only as a candidate cluster
- **AND** semantic similarity alone SHALL NOT establish that the evidence represents the same underlying concept gap

#### Scenario: Candidate evidence is classified
- **WHEN** the constrained semantic classifier receives a candidate group
- **THEN** it SHALL select only from the supported cluster types `same_underlying_gap`, `same_wrong_approach`, `same_prerequisite_weakness`, `same_execution_pattern`, `related_distinct_subgaps`, or `unrelated`
- **AND** it SHALL split the candidate group when one supported relationship does not accurately describe all included evidence
- **AND** it SHALL prefer splitting or a non-exact relationship over an over-broad `same_underlying_gap` classification

#### Scenario: Same underlying gap is established
- **WHEN** the classifier assigns `same_underlying_gap`
- **THEN** all included evidence SHALL require the same principle, relationship, condition, or theorem
- **AND** all included evidence SHALL show the same misunderstood element and the same or equivalent student mental model
- **AND** one targeted corrective explanation and one precise concept-gap statement SHALL accurately apply to every included evidence item

#### Scenario: Evidence is related but requires different corrections
- **WHEN** candidate evidence concerns related concepts but requires different targeted corrective explanations
- **THEN** the classifier SHALL classify the evidence as `related_distinct_subgaps` or split it into narrower exact-gap clusters
- **AND** it SHALL NOT classify the complete candidate as `same_underlying_gap`

#### Scenario: Shared behavior crosses distinct concepts
- **WHEN** evidence from distinct concepts shares a solving behavior, prerequisite weakness, or execution failure
- **THEN** the classifier SHALL use `same_wrong_approach`, `same_prerequisite_weakness`, or `same_execution_pattern` as appropriate
- **AND** it SHALL NOT convert the shared behavior into a concept-level gap

### Requirement: Two-Stage Conceptual Synthesis
The system SHALL form local recurring concept gaps before synthesizing broader subject-level conceptual patterns.

#### Scenario: Local concept gaps are formed
- **WHEN** question diagnosis evidence is analyzed for recurrence
- **THEN** the first stage SHALL cluster the same or closely equivalent conceptual gaps within a canonical chapter/topic context
- **AND** recurrence SHALL require support from at least two distinct diagnosis reports

#### Scenario: Broader patterns are formed
- **WHEN** validated local concept gaps are available
- **THEN** the second stage SHALL compare those local gaps across distinct chapter/topic contexts
- **AND** it SHALL create a broader pattern only when they exhibit the same type of conceptual reasoning failure
- **AND** the broader pattern SHALL preserve references to every component local gap

#### Scenario: Raw evidence is not directly over-generalized
- **WHEN** the system creates a broader pattern
- **THEN** it SHALL synthesize from validated local concept gaps rather than treating one broad semantic-neighbor group of raw question diagnoses as a subject-level pattern

### Requirement: Auditable Exact-Gap Classification
Every `same_underlying_gap` classification SHALL include enough structured information to audit why the evidence represents one exact concept gap.

#### Scenario: Exact-gap cluster is returned
- **WHEN** the classifier returns a `same_underlying_gap` cluster
- **THEN** the cluster SHALL include a canonical chapter, canonical topic, precise concept-gap statement, shared misconception, targeted corrective concept, evidence identifiers, classification confidence, and classification rationale
- **AND** the rationale SHALL explain why one precise gap statement and one corrective concept apply to all included evidence

#### Scenario: Exact-gap cluster is validated
- **WHEN** an exact-gap cluster lacks the required structured reasoning, uses a title that is only a chapter-wide or topic-wide weakness, or contains evidence requiring different corrective concepts
- **THEN** the system SHALL reject, split, or reclassify the cluster before computing report content

### Requirement: Recurring Gaps as Exact Concept Diagnosis
The Recurring Gaps section SHALL identify the same or closely equivalent conceptual gaps consistently observed while the student solves problems within a canonical chapter/topic context across distinct diagnosis reports.

#### Scenario: Recurring gap entry is eligible
- **WHEN** a validated `same_underlying_gap` cluster is supported by at least two distinct diagnosis reports
- **THEN** it SHALL be eligible for the Recurring Gaps section
- **AND** the entry SHALL identify its canonical chapter, canonical topic, precise concept gap, shared misconception, supporting report count, supporting question count, same-gap reasoning, compact evidence references, and instructional priority or impact
- **AND** the entry SHALL include a concise action for the student and a concise action for the teacher

#### Scenario: Candidate spans distinct chapter/topic contexts
- **WHEN** related conceptual evidence spans different chapter/topic contexts
- **THEN** the complete cross-context group SHALL NOT appear as one Recurring Gap
- **AND** the system SHALL first preserve its local chapter/topic concept gaps and then evaluate them for Broader Related Patterns

#### Scenario: Recurring Gaps avoid section duplication
- **WHEN** the Recurring Gaps section is rendered
- **THEN** it SHALL diagnose the local recurring concepts without reproducing full question-level diagnoses or broader cross-gap synthesis
- **AND** a broader synthesized pattern SHALL NOT be duplicated as a local recurring gap
- **AND** a broader pattern MAY reference local recurring gaps as its component evidence without restating their full entries

### Requirement: Recurring Gaps Quality Validation
The system SHALL validate each Recurring Gaps entry against its exact concept-diagnosis objective.

#### Scenario: Recurring gap entry is accepted
- **WHEN** an entry maps to a validated recurring `same_underlying_gap` cluster, identifies one precise concept and misconception, provides same-gap reasoning and evidence counts, and remains distinct from broader or non-conceptual patterns
- **THEN** the system SHALL accept the entry

#### Scenario: Recurring gap entry is over-broad
- **WHEN** an entry combines evidence only because it shares a chapter or topic, requires multiple different corrective concepts, represents a general solving behavior, or is supported by only one diagnosis report
- **THEN** the system SHALL reject, split, reclassify, or move the entry before rendering the final report

### Requirement: Broader Related Patterns as Cross-Context Synthesis
The Broader Related Patterns section SHALL identify the same type of conceptual reasoning gap when it is demonstrated by distinct local concept gaps across different chapters or topics in the subject.

#### Scenario: Broader pattern is eligible
- **WHEN** at least two validated local concept gaps from distinct chapter/topic contexts share the same conceptual reasoning failure
- **THEN** the system SHALL be eligible to create a Broader Related Pattern
- **AND** the pattern SHALL name its component local gaps and their chapter/topic contexts
- **AND** it SHALL explain the conceptual reasoning operation shared across those contexts
- **AND** it SHALL state the supporting report, question, and chapter/topic counts

#### Scenario: Broader pattern remains actionable
- **WHEN** a Broader Related Pattern is rendered
- **THEN** it SHALL explain the additional instructional value gained by connecting the local gaps
- **AND** it SHALL include one concise cross-context action for the student and one concise cross-context action for the teacher

#### Scenario: Shared syllabus label is insufficient
- **WHEN** local gaps share only a subject, chapter, topic label, vocabulary, or formula family without the same conceptual reasoning failure
- **THEN** the system SHALL NOT create a Broader Related Pattern from them

#### Scenario: Non-conceptual similarity is insufficient
- **WHEN** evidence shares only calculation mistakes, careless execution, prompt misreading, or a generic need for practice
- **THEN** the system SHALL NOT present that similarity as a Broader Related Pattern

### Requirement: Broader Related Patterns Quality Validation
The system SHALL validate every broader pattern against its cross-chapter/topic conceptual-synthesis objective.

#### Scenario: Broader pattern is accepted
- **WHEN** a pattern references at least two distinct local concept gaps from different chapter/topic contexts, explains their shared conceptual reasoning failure, preserves their differences, and supplies evidence scope and actions
- **THEN** the system SHALL accept the pattern

#### Scenario: Broader pattern is unsupported
- **WHEN** a pattern is based only on semantic proximity, a shared syllabus label, raw question evidence without validated local gaps, or a non-conceptual behavior
- **THEN** the system SHALL reject or regenerate the pattern

### Requirement: Overall Summary as Decision Summary
The Overall Summary SHALL concisely present the strongest and most actionable conclusions from the detailed profile without replacing or duplicating the detailed diagnostic sections.

#### Scenario: Overall Summary is generated
- **WHEN** a longitudinal profile contains recurring evidence
- **THEN** the Overall Summary SHALL state the evidence scope, including diagnosis-report count and diagnosed-question count
- **AND** it SHALL identify no more than two highest-priority exact recurring concept gaps when such gaps exist
- **AND** it SHALL identify no more than one highest-priority broader related pattern when such a pattern exists
- **AND** it SHALL state one immediate student focus and one immediate teacher focus

#### Scenario: Exact gap is summarized
- **WHEN** the Overall Summary names an exact recurring concept gap
- **THEN** the named gap SHALL correspond to a validated recurring `same_underlying_gap` cluster
- **AND** the summary SHALL identify its chapter and topic
- **AND** the summary SHALL communicate why it is prioritized using evidence strength, foundational importance, severity, or instructional impact

#### Scenario: Broader pattern is summarized
- **WHEN** the Overall Summary names a broader related pattern
- **THEN** it SHALL explicitly identify the finding as a broader pattern connecting distinct gaps
- **AND** it SHALL NOT describe the pattern as one exact concept gap

#### Scenario: Summary avoids detail duplication
- **WHEN** the Overall Summary is rendered
- **THEN** it SHALL omit full question-level diagnosis narratives, exhaustive evidence references, and detailed actions
- **AND** those details SHALL remain in their uniquely responsible report sections

#### Scenario: Summary claims remain proportional to evidence
- **WHEN** the available history establishes recurrence across reports but does not establish a temporal trend
- **THEN** the Overall Summary SHALL use cross-report recurrence language
- **AND** it SHALL NOT use unsupported trend language such as persistent, improving, worsening, or resolved

### Requirement: Overall Summary Quality Validation
The system SHALL validate the Overall Summary against its unique objective and the validated longitudinal evidence pack.

#### Scenario: Summary is accepted
- **WHEN** the Overall Summary contains only supported findings, distinguishes exact gaps from broader patterns, states evidence scope, provides immediate student and teacher focus, and avoids detailed-section duplication
- **THEN** the system SHALL accept the Overall Summary as achieving its section objective

#### Scenario: Summary overstates or conflates evidence
- **WHEN** the Overall Summary presents related-but-distinct gaps as one exact gap, omits evidence scope, introduces an unsupported finding, or makes an unsupported temporal claim
- **THEN** the system SHALL reject or regenerate the report

### Requirement: Restricted Written Report Structure
The written longitudinal profile SHALL contain only the analytical sections Overall Summary, Recurring Gaps, and Broader Related Patterns, followed by an Evidence Appendix.

#### Scenario: Report is rendered
- **WHEN** the system produces the written profile
- **THEN** it SHALL render the sections in the order Overall Summary, Recurring Gaps, Broader Related Patterns, and Evidence Appendix
- **AND** it SHALL NOT render separate Isolated or Early Indicators, Study Priorities, Teacher Intervention Notes, Chapter/Topic Weakness Map, or other analytical sections

#### Scenario: Actionability is preserved
- **WHEN** separate study-priority and teacher-intervention sections are omitted
- **THEN** the Recurring Gaps and Broader Related Patterns entries SHALL contain their own concise student and teacher actions
- **AND** the Overall Summary SHALL identify only the immediate highest-priority focus

### Requirement: Evidence Appendix
The Evidence Appendix SHALL preserve auditable question-level support for the profile without repeating that detail throughout the analytical sections.

#### Scenario: Evidence row is rendered
- **WHEN** a question diagnosis contributes to the profile evidence pack
- **THEN** the appendix SHALL include its question analysis, test name, question number, subject, and test date
- **AND** the appendix SHALL preserve a traceable reference to the source diagnosis report

#### Scenario: Required appendix metadata is unavailable
- **WHEN** the test date, test name, question number, or subject is unavailable
- **THEN** the system SHALL mark the missing field explicitly
- **AND** it SHALL NOT substitute the diagnosis generation date for the test date without labelling the substitution

#### Scenario: Analytical section cites evidence
- **WHEN** a Recurring Gap or Broader Related Pattern cites its support
- **THEN** it SHALL use compact test and question references
- **AND** the full associated question analysis SHALL remain in the Evidence Appendix
