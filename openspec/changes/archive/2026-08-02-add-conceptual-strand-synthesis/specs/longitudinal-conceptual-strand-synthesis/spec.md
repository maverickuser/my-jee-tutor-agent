## ADDED Requirements

### Requirement: Conceptual strand between diagnosis and recurring gap
The system SHALL represent related question diagnoses through a conceptual strand that names one precise missing mental model or conceptual operation, rather than requiring identical question-level diagnoses.

#### Scenario: Different manifestations share one missing model
- **WHEN** evidence from multiple questions exhibits different symptoms that are corrected by one coherent conceptual model
- **THEN** the system SHALL be able to place those manifestations in one conceptual strand

#### Scenario: Surface similarity is insufficient
- **WHEN** evidence shares vocabulary or a syllabus label but requires different corrective models
- **THEN** the system SHALL keep the evidence in separate strands

### Requirement: Chapter-family bounded synthesis
The system SHALL form local conceptual strands within one normalized chapter or closely related chapter-level concept family and SHALL preserve every evidence item's original chapter and topic.

#### Scenario: Related chapter labels
- **WHEN** evidence is labelled `Electrostatics` and `Electrostatics and Capacitance` and both concerns one capacitor-system mental model
- **THEN** the system SHALL permit one chapter-family conceptual strand while preserving the distinct source labels

#### Scenario: Unrelated chapter families
- **WHEN** evidence belongs to unrelated chapter-level concept families
- **THEN** the system SHALL NOT combine it into one local conceptual strand

### Requirement: Auditable strand manifestations
Every conceptual strand SHALL include a manifestation for each supporting evidence ID that explains how that question expresses the strand's missing mental model.

#### Scenario: Complete manifestation coverage
- **WHEN** a strand references three evidence IDs
- **THEN** its manifestation map SHALL reference exactly those three evidence IDs

#### Scenario: Unsupported manifestation
- **WHEN** a manifestation references evidence outside the strand or stored evidence index
- **THEN** deterministic validation SHALL reject the strand

### Requirement: Cross-report recurrence
The system SHALL report a conceptual strand as recurring only when supporting evidence spans at least two distinct diagnosis reports and confidence is medium or high.

#### Scenario: Several questions in one paper
- **WHEN** a conceptual strand contains several questions from one diagnosis report only
- **THEN** it SHALL NOT be reported as longitudinally recurring

#### Scenario: Different manifestations across papers
- **WHEN** a conceptual strand contains related manifestations from at least two diagnosis reports
- **THEN** it SHALL be eligible as a recurring gap

### Requirement: Non-conceptual evidence exclusion
The system SHALL distinguish conceptual evidence from calculation execution, ambiguous or flawed questions, insufficient evidence, and unrelated misconceptions.

#### Scenario: Calculation slip
- **WHEN** diagnosis evidence says the physical model and setup were correct but the final arithmetic was wrong
- **THEN** the system SHALL NOT use that item to establish a conceptual strand

#### Scenario: Ambiguous question
- **WHEN** diagnosis evidence attributes the result to a flawed or ambiguous question rather than a student misconception
- **THEN** the system SHALL exclude that item from recurring conceptual gaps

### Requirement: Broader patterns derive from recurring strands
The system SHALL synthesize broader related patterns only from validated recurring conceptual strands spanning at least two distinct chapter or concept families.

#### Scenario: Cross-family reasoning operation
- **WHEN** two recurring strands from distinct concept families share a precise reasoning failure and common corrective principle
- **THEN** the system SHALL be able to report a broader related pattern with each strand's distinct manifestation

#### Scenario: Generic behavior label
- **WHEN** the only commonality is formula recall, carelessness, vocabulary, or syllabus proximity
- **THEN** the system SHALL NOT report a broader conceptual pattern

### Requirement: Insight-led overall summary
The Overall Summary SHALL prioritize the strongest recurring conceptual strands and broader patterns, explain their significance, and provide distinct student and teacher next actions.

#### Scenario: Reportable strands exist
- **WHEN** one or more validated recurring strands exist
- **THEN** the summary SHALL name the highest-priority insights rather than only state evidence counts

#### Scenario: No supported strand exists
- **WHEN** no strand meets the evidence threshold
- **THEN** the summary SHALL state the limitation without inventing a finding

### Requirement: Actionable recurring-gap content
Each Recurring Gaps entry SHALL include the missing mental model, related chapter/topics, evidence breadth, manifestations across papers, one corrective model, a student action, a teacher intervention, and a verification check.

#### Scenario: Teacher can test correction
- **WHEN** a recurring gap is rendered
- **THEN** the report SHALL provide a concrete check that can determine whether the student corrected the underlying model

### Requirement: Compact traceable evidence appendix
The Evidence Appendix SHALL provide compact evidence records containing test name, test date or explicit unavailability, question number, subject, chapter/topic, diagnostic claim, and supported finding IDs.

#### Scenario: Evidence supports a finding
- **WHEN** an appendix item supports a recurring strand or broader pattern
- **THEN** the appendix SHALL list the corresponding finding ID

#### Scenario: Avoid question-report duplication
- **WHEN** an appendix item is rendered
- **THEN** it SHALL NOT reproduce the complete likely-reasoning, why-wrong, and recommendation paragraphs

### Requirement: Evidence-rich synthesis regression
The quality suite SHALL include representative multi-paper evidence that proves the system produces meaningful conceptual strands and rejects unsupported broad grouping.

#### Scenario: Physics-like capacitor evidence
- **WHEN** evidence across papers covers charge conservation, node modeling, voltage constraints, and equilibrium in capacitor systems
- **THEN** the quality test SHALL require a recurring capacitor-system conceptual strand

#### Scenario: Empty-insight regression
- **WHEN** the representative evidence fixture is analyzed
- **THEN** a report containing only an empty-recurring-gap message SHALL fail the quality test

### Requirement: Untrusted classifier output repair
The system SHALL reconcile semantic classifier references against the authoritative input evidence before strict conceptual-strand validation and SHALL NOT fail a profile request solely because the classifier invents an evidence ID or merges chapter families.

#### Scenario: Invented evidence IDs
- **WHEN** a classifier strand or exclusion references evidence IDs absent from the input evidence index
- **THEN** the system SHALL remove those references and continue with the supported evidence

#### Scenario: Cross-family strand
- **WHEN** a classifier strand contains evidence from multiple normalized chapter families
- **THEN** the system SHALL retain only a coherent supported family, derive its labels and topics from authoritative evidence, and continue without raising a cross-family validation error

#### Scenario: Strand loses all supported evidence
- **WHEN** classifier-output repair leaves a strand with no authoritative evidence
- **THEN** the system SHALL drop that strand rather than fail the profile request

#### Scenario: Missing manifestation for retained evidence
- **WHEN** a retained authoritative evidence item lacks a valid classifier manifestation
- **THEN** the system SHALL use the source diagnostic claim as its auditable manifestation before strict validation
