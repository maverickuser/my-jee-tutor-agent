# Student Actionable Insights Specification

## Purpose

Defines the structured-evidence profile flow that turns recurring student mistakes into a compact, prioritized, subject-specific PDF report.

## Requirements

### Requirement: Authoritative Structured Evidence Input
The system SHALL use structured diagnosis JSON as the authoritative source for actionable-insight analysis.

#### Scenario: Subject history is requested
- **WHEN** the profile task receives a valid student and subject request
- **THEN** the system SHALL query diagnosis metadata for that student and subject
- **AND** load each referenced structured diagnosis JSON from `diagnosis_json_s3_uri`
- **AND** SHALL NOT require PDF or Markdown diagnosis artifacts for synthesis

#### Scenario: Question evidence is constructed
- **WHEN** a structured diagnosis report is loaded
- **THEN** the system SHALL construct ordered question evidence from its chapter, topic, question number, exact concept gap, likely thought, why wrong, and deep-dive fields
- **AND** assign each question an evidence identity of `<diagnosis_report_id>:q<ordinal>`

#### Scenario: Referenced JSON cannot be loaded
- **WHEN** a diagnosis metadata record references missing, malformed, or inaccessible structured JSON
- **THEN** the system SHALL exclude that report from synthesis
- **AND** record an internal evidence-loading error
- **AND** SHALL NOT substitute PDF or Markdown text as authoritative evidence

### Requirement: Embedding-Assisted Candidate Discovery
The system SHALL use compatible question embeddings to discover candidate recurring patterns but SHALL NOT treat embedding similarity as sufficient validation.

#### Scenario: Cached embedding is compatible
- **WHEN** a question has a DynamoDB embedding record matching its `diagnosis_json_s3_uri`, evidence identity, configured embedding model, input version, and current embedding text hash
- **THEN** the system SHALL reuse that embedding for candidate discovery

#### Scenario: Cached embedding is missing or stale
- **WHEN** no compatible embedding exists or its text hash is stale
- **THEN** the system SHALL create a current embedding through the existing evidence embedding service
- **AND** cache it using the existing DynamoDB record contract

#### Scenario: Candidate questions are semantically similar
- **WHEN** embedding similarity proposes a candidate group
- **THEN** the system SHALL validate the group against the structured JSON evidence
- **AND** require a comparable failure stage, shared observable behavior, and one shared preventive action before producing an insight

#### Scenario: Embeddings are discoverable only by scanning
- **WHEN** the system needs to identify reports for a student and subject
- **THEN** it SHALL use the diagnosis metadata store and referenced S3 JSON locations
- **AND** SHALL NOT scan or prefix-filter the embedding table to discover student evidence

### Requirement: Question Failure Identification
The system SHALL identify the earliest meaningful divergence between the described student approach and the correct solution for each wrong question.

#### Scenario: Concept is not used
- **WHEN** the correct solution requires a rule that is absent from the described approach
- **THEN** the system SHALL classify the failure as `concept_not_applied`
- **AND** record the missing rule as the question-level concept gap

#### Scenario: Concept is used incorrectly
- **WHEN** the described approach invokes the relevant concept with an invalid formula, condition, sign, branch, or interpretation
- **THEN** the system SHALL classify the failure as `concept_applied_incorrectly`

#### Scenario: Concept is used incompletely
- **WHEN** the described approach correctly begins a required method but omits one or more required cases, boundaries, branches, terms, or validation steps
- **THEN** the system SHALL classify the failure as `concept_applied_incompletely`

#### Scenario: Correct concept with execution failure
- **WHEN** the described method and concept are correct but arithmetic, algebra, transcription, or final-answer selection causes the wrong result
- **THEN** the system SHALL classify the failure separately as an execution or attention error
- **AND** SHALL NOT mislabel it as missing conceptual knowledge

### Requirement: Evidence and Confidence Preservation
The system SHALL preserve evidence provenance and confidence internally without adding uncertainty disclaimers to the default student report.

#### Scenario: Student working is available
- **WHEN** the input contains the student's written reasoning or intermediate steps
- **THEN** the system SHALL ground the divergence in those steps
- **AND** may assign high confidence when the evidence directly supports the diagnosis

#### Scenario: Only inferred analysis is available
- **WHEN** the input describes what the student “likely” or “probably” thought without providing written working
- **THEN** the system SHALL mark the diagnosis as inferred
- **AND** use that confidence in internal ranking and metadata
- **AND** phrase student advice prospectively without claiming the inferred thought process as fact
- **AND** SHALL NOT display a default disclaimer such as “reasoning is inferred” in the student report

### Requirement: Cross-Question Pattern Formation
The system SHALL form a recurring pattern only from question failures that share a reasoning behavior and a preventive action.

#### Scenario: Failures share behavior and prevention
- **WHEN** failures from at least two independent questions occur at a comparable reasoning stage
- **AND** exhibit the same observable behavior
- **AND** can be prevented by the same student action
- **THEN** the system SHALL be permitted to group them into one recurring insight
- **AND** preserve every supporting question reference

#### Scenario: Questions only share a chapter
- **WHEN** failures occur in the same chapter or topic but require different corrective actions
- **THEN** the system SHALL keep them as separate patterns

#### Scenario: Questions use different concepts but share prevention
- **WHEN** question-level concepts differ but the failures share an observable behavior and one natural preventive action
- **THEN** the system MAY group them at the behavioral level
- **AND** SHALL preserve the distinct question-level concept gaps beneath that grouping

#### Scenario: Pattern has only one supporting question
- **WHEN** a failure appears in only one question
- **THEN** the system SHALL retain it as question-level feedback
- **AND** SHALL NOT describe it as a recurring cross-question pattern

### Requirement: Actionable Insight Translation
The system SHALL translate every selected recurring pattern into a concise, proactive student action.

#### Scenario: Abstract diagnostic label exists
- **WHEN** the internal pattern label uses analytical language such as “incomplete solution-space coverage”
- **THEN** the student-visible output SHALL replace it with plain language describing the observed mistake
- **AND** provide a short preventive action

#### Scenario: Student action is generated
- **WHEN** a recurring pattern is selected for the report
- **THEN** its heading SHALL be a short self-question the student can mentally ask during an exam
- **AND** its `Do` field SHALL specify one immediate, observable behavior the student can perform in rough work
- **AND** its `Ask this when you see` field SHALL name recognizable subject-specific visual or wording cues

#### Scenario: Advice lacks a trigger
- **WHEN** proposed advice is generic, such as “be careful” or “revise more”
- **THEN** the system SHALL reject or rewrite it to include a recognizable question cue and a concrete response

#### Scenario: Advice uses teacher or analytical language
- **WHEN** a proposed heading or instruction uses abstract diagnostic terminology, unexplained jargon, or language unsuitable for a 16-year-old student
- **THEN** the system SHALL rewrite it as a simple self-question and direct action
- **AND** preserve the precise analytical label only in internal metadata

### Requirement: Compact Student Report
The system SHALL produce a compact subject-wise report prioritized for immediate student use.

#### Scenario: Default report generation
- **WHEN** recurring patterns are available
- **THEN** the report SHALL contain no more than three prioritized insights by default
- **AND** each student-visible insight SHALL contain a self-question heading, `Do`, and `Ask this when you see`
- **AND** each `Do` instruction SHALL state one immediate preventive behavior
- **AND** each usage cue SHALL name recognizable subject-specific question features

#### Scenario: Insight evidence is retained internally
- **WHEN** an insight is included in the report
- **THEN** its internal metadata SHALL retain supporting evidence references, question-level gaps, source provenance, and confidence
- **AND** the default student report SHALL omit internal pattern labels, evidence codes, and confidence disclaimers

#### Scenario: No recurring pattern is supported
- **WHEN** no pattern has evidence from at least two independent questions
- **THEN** the report SHALL state that no recurring pattern is established
- **AND** return only the most important question-level actions

### Requirement: Insight Prioritization
The system SHALL prioritize supported insights using recurrence, likely mark impact, and diagnostic confidence.

#### Scenario: More than three patterns qualify
- **WHEN** more than three recurring patterns satisfy the grouping requirements
- **THEN** the system SHALL select the three with the strongest combination of recurrence, impact, and confidence

#### Scenario: High-frequency pattern has weak evidence
- **WHEN** a frequently mentioned pattern is based primarily on speculative descriptions
- **THEN** the system SHALL lower its confidence or priority
- **AND** SHALL NOT present it more strongly than directly evidenced patterns

### Requirement: Chapter Weightage Prioritization
The system SHALL use the versioned subject chapter-weightage JSON published under the configured S3 curriculum prefix to focus the report when mistakes are concentrated.

#### Scenario: Repeated mistakes occur in weighted chapters
- **WHEN** at least two diagnosed questions map to the same curriculum chapter
- **THEN** the student report SHALL list that chapter in `Chapters to fix first`
- **AND** order eligible chapters by combined JEE weightage, then mistake count
- **AND** limit the list to five chapters

#### Scenario: Weightage data is unavailable or no chapter is repeated
- **WHEN** curriculum JSON cannot be loaded or no chapter contains at least two mistakes
- **THEN** actionable-insight generation SHALL continue without a chapter-priority section
- **AND** SHALL NOT invent a weightage value or chapter mapping

### Requirement: Reusable Subject Application
The system SHALL apply the same analysis method to reports from any academic subject while preserving subject-specific triggers and actions.

#### Scenario: Mathematics reports are analyzed
- **WHEN** the evidence involves modulus, branches, piecewise boundaries, identity conditions, or candidate verification
- **THEN** the generated actions SHALL name the relevant mathematical triggers rather than use only generic study advice

#### Scenario: Another subject is analyzed
- **WHEN** the supplied reports concern a non-Mathematics subject
- **THEN** the system SHALL retain the same divergence, classification, grouping, prioritization, and translation process
- **AND** derive triggers and actions from that subject's evidence

### Requirement: Existing Profile Task Replacement
The system SHALL replace the current profile synthesis and report behavior with actionable-insight generation behind the existing profile application boundary.

#### Scenario: Existing profile task is invoked
- **WHEN** a caller invokes `profile` or a supported profile-task alias
- **THEN** the system SHALL run the actionable-insight evidence, embedding, validation, prioritization, and rendering flow
- **AND** SHALL NOT run the previous longitudinal profile synthesis and report renderer

#### Scenario: Existing evidence infrastructure is configured
- **WHEN** the replacement profile flow loads evidence and embeddings
- **THEN** it SHALL reuse the existing diagnosis metadata store, S3 structured-diagnosis artifact store, and evidence embedding service
- **AND** SHALL preserve existing diagnosis JSON and DynamoDB embedding record formats

#### Scenario: No usable evidence exists
- **WHEN** no usable structured diagnosis questions are available for the requested student and subject
- **THEN** the replacement profile task SHALL return a successful no-history response
- **AND** SHALL NOT invent an actionable insight

### Requirement: Profile Report PDF Artifact
The system SHALL render and upload the student-facing actionable-insights report as a PDF before returning a successful report response.

#### Scenario: PDF target URI is derived
- **WHEN** a report is generated for a student and subject
- **THEN** the target URI SHALL be `s3://jee-tutor-agent-terraform-state/profile-reports/<student-name>+<student-id>/<subject_name>/<subject_name>_profile_report.pdf`
- **AND** the plus sign between student name and student ID SHALL be literal
- **AND** the same sanitized subject component SHALL be used in both directory and filename

#### Scenario: Path components require sanitization
- **WHEN** student name, student ID, or subject contains characters outside letters, numbers, dot, underscore, or hyphen
- **THEN** each unsafe run SHALL be replaced by an underscore
- **AND** leading and trailing dot, underscore, and hyphen characters SHALL be removed from each component
- **AND** a component that sanitizes to blank SHALL cause a handled validation error

#### Scenario: PDF is rendered
- **WHEN** actionable insights pass output validation
- **THEN** the PDF SHALL contain the student identity, subject, and no more than three student-visible insights
- **AND** each insight SHALL contain its self-question heading, `Do`, and `Ask this when you see`
- **AND** the PDF SHALL exclude internal evidence IDs, source URIs, confidence values, diagnostic labels, and inference disclaimers

#### Scenario: PDF upload succeeds
- **WHEN** PDF rendering and upload to the required S3 URI succeed
- **THEN** the profile-task response SHALL include `profile_report_pdf_uri` equal to the uploaded URI
- **AND** the task MAY return the structured student report in the response

#### Scenario: PDF rendering or upload fails
- **WHEN** PDF rendering or S3 upload fails
- **THEN** the profile task SHALL return a handled artifact error
- **AND** SHALL NOT return a successful report response or `profile_report_pdf_uri`
