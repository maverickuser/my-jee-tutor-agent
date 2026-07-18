## ADDED Requirements

### Requirement: Student Diagnosis Report Metadata
The system SHALL maintain report-level metadata for successful profile-capable diagnosis reports.

#### Scenario: Successful diagnosis metadata is available
- **WHEN** a guardrail-approved diagnosis report is associated with a parseable S3 image prefix and recipient email
- **THEN** the system SHALL store a student diagnosis metadata record
- **AND** the metadata record SHALL include parsed student id, recipient email, parsed student name, parsed subject, parsed test or paper name, diagnosis report id, diagnosis date, S3 path of the structured JSON diagnosis report, and number of questions analysed
- **AND** the metadata record MAY include S3 paths for human-readable PDF or Markdown artifacts

#### Scenario: Student metadata is parsed from S3 path
- **WHEN** the image S3 prefix or key follows `users/{student_id}/{student_name}/tests/{test_name}/subjects/{subject}/questions/...`
- **THEN** the system SHALL parse `student_id`, `student_name`, `test_name`, and `subject` from those path segments
- **AND** the system SHALL store recipient email separately as the metadata email field

#### Scenario: JSON report artifact is stored beside the PDF artifact
- **WHEN** a successful profile-capable diagnosis writes analysis artifacts to S3
- **THEN** the system SHALL store the structured JSON diagnosis report in the same S3 prefix as the PDF artifact
- **AND** the JSON artifact path SHALL preserve the parsed student id, student name, test name, and subject path segments from the image prefix
- **AND** the JSON artifact SHALL use the same artifact basename as the PDF with a `.json` suffix

#### Scenario: Metadata is scoped by subject
- **WHEN** student diagnosis metadata is queried for a subject
- **THEN** the system SHALL return only metadata records associated with that recipient email and subject
- **AND** metadata from other subjects SHALL NOT be included

#### Scenario: Structured JSON reports provide question evidence
- **WHEN** profile analysis loads a metadata record
- **THEN** the system SHALL load the structured JSON diagnosis report from the referenced S3 path
- **AND** the JSON report SHALL provide question-level evidence including diagnosis report id, question number, chapter, topic, likely student thought, why that thought was wrong, exact concept gap, and deep-dive recommendation
- **AND** the loaded question count SHALL match the metadata record's number of questions analysed

#### Scenario: Sensitive payloads are excluded
- **WHEN** diagnosis metadata or structured JSON reports are stored or returned for profile analysis
- **THEN** the system SHALL NOT include image data URIs, base64 image payloads, full model request bodies, full raw model responses, or stack traces
- **AND** recipient email SHALL appear only in the metadata email field and not in JSON diagnosis question evidence, prompts, operational logs, or telemetry

### Requirement: Profile Request Scope
The system SHALL generate longitudinal profile reports only when explicitly requested for one student and one subject.

#### Scenario: Profile report is requested
- **WHEN** a caller requests a longitudinal profile report with a student email and subject
- **THEN** the system SHALL analyze diagnosis history for only that recipient email and subject
- **AND** the system SHALL return a written profile report

#### Scenario: Profile has no diagnosis history
- **WHEN** a caller requests a profile report for a student and subject with no stored diagnosis evidence
- **THEN** the system SHALL return a handled response explaining that no diagnosis history is available
- **AND** the system SHALL NOT invent profile insights

#### Scenario: Profile has one diagnosis report
- **WHEN** profile evidence exists from only one diagnosis report
- **THEN** the system SHALL identify gaps as isolated or early indicators
- **AND** the system SHALL NOT label any gap as recurring

### Requirement: Semantic Gap Analysis
The system SHALL use embedding-backed semantic analysis followed by mandatory LLM cluster classification to cluster same or related learning gaps across structured diagnosis reports.

#### Scenario: Evidence items are prepared for clustering
- **WHEN** student subject history is loaded from JSON diagnosis reports
- **THEN** the system SHALL prepare compact evidence items for semantic analysis
- **AND** each evidence item SHALL include evidence id, diagnosis report id, question number, chapter, topic, exact concept gap, likely student thought, why that thought was wrong, and deep-dive recommendation

#### Scenario: Missing evidence embeddings are created first
- **WHEN** semantic gap analysis starts for a requested profile
- **THEN** the system SHALL first ensure an embedding exists for every compact evidence item in the requested student and subject history
- **AND** the embedding input SHALL be derived from the evidence item's subject, chapter, topic, exact concept gap, likely student thought, why that thought was wrong, and deep-dive recommendation
- **AND** the system SHALL reuse existing embeddings when the embedding model, embedding input version, and embedding text hash match the current evidence item
- **AND** the system SHALL create embeddings only for evidence items that do not already have a matching stored embedding
- **AND** stored embeddings SHALL be keyed by the structured JSON diagnosis report path, evidence id, embedding model, and embedding input version

#### Scenario: Embedding similarity proposes candidate clusters
- **WHEN** all requested evidence items have embeddings
- **THEN** the system SHALL compute cosine similarity between evidence embeddings within the requested student and subject scope
- **AND** the system SHALL use cosine similarity to propose candidate same-gap or related-gap groups for classification
- **AND** deterministic normalized-text matches MAY be added as additional candidates but SHALL NOT replace embedding similarity

#### Scenario: Semantic clusters are produced
- **WHEN** candidate clusters have been proposed from embedding similarity
- **THEN** the system SHALL call an LLM classifier to classify cluster type
- **AND** the LLM classifier SHALL identify same underlying concept gaps, same wrong approaches, same prerequisite weaknesses, same execution patterns, related-but-distinct subgaps, or unrelated mistakes when supported by evidence
- **AND** each cluster SHALL preserve evidence ids for the source diagnosis rows
- **AND** the system SHALL NOT treat unclassified embedding-neighbor groups as final semantic clusters

#### Scenario: Semantic clusters are validated
- **WHEN** semantic gap analysis returns clusters
- **THEN** the system SHALL verify that every evidence id exists in the requested student and subject evidence set
- **AND** the system SHALL reject or repair clusters that invent evidence, cite a different subject, duplicate evidence in incompatible clusters, or omit required cluster fields

### Requirement: Mistake Grouping
The system SHALL build a longitudinal evidence pack from validated semantic clusters and source diagnosis evidence.

#### Scenario: Chapter and topic map is built
- **WHEN** a profile report is generated
- **THEN** the system SHALL build a chapter and topic map under the requested subject
- **AND** the map SHALL distinguish exact recurring gaps, broader related recurring patterns, and isolated or early-indicator gaps

#### Scenario: Multiple questions in one report
- **WHEN** the same concept gap appears in multiple questions from one diagnosis report only
- **THEN** the system MAY use the count as severity evidence
- **AND** the system SHALL NOT classify the gap as recurring unless it appears in at least two separate diagnosis reports

### Requirement: Recurring Gap Classification
The system SHALL classify recurring gaps using diagnosis report count rather than time windows.

#### Scenario: Gap appears in two reports
- **WHEN** a validated semantic cluster is supported by evidence from at least two separate diagnosis reports
- **THEN** the system SHALL classify the gap as recurring
- **AND** the report SHALL include the number of supporting diagnosis reports

#### Scenario: Gap appears in one report
- **WHEN** a concept gap is supported by evidence from only one diagnosis report
- **THEN** the system SHALL classify the gap as isolated or an early indicator
- **AND** the system SHALL NOT use persistent-weakness language for that gap

#### Scenario: Time windows are not requested
- **WHEN** recurring gaps are computed
- **THEN** the system SHALL base recurrence on diagnosis report count
- **AND** the system SHALL NOT require last-7-day, last-30-day, or other time-window filtering for recurrence

### Requirement: Written Longitudinal Report
The system SHALL use a separate profile analysis agent to produce a written per-subject profile report useful to both students and teachers.

#### Scenario: Report sections are produced
- **WHEN** a profile report is generated from diagnosis history
- **THEN** the report SHALL include an overall summary, most important recurring gaps, chapter/topic weakness map, mistake pattern analysis, recommended study priorities, teacher intervention notes, and evidence appendix

#### Scenario: Profile agent is separate from diagnosis agent
- **WHEN** a requested longitudinal profile report is generated
- **THEN** the system SHALL use a profile analysis flow separate from the current-attempt diagnosis agent
- **AND** the profile analysis flow SHALL NOT invoke vision diagnosis tools or re-diagnose source images

#### Scenario: Student-facing priorities are included
- **WHEN** recurring or isolated gaps are reported
- **THEN** the report SHALL explain what the student should study next
- **AND** the report SHALL prioritize recurring gaps before isolated gaps unless an isolated gap is explicitly marked as foundational

#### Scenario: Teacher-facing intervention notes are included
- **WHEN** recurring or important gaps are reported
- **THEN** the report SHALL include teacher intervention notes that describe what to reteach, drill, verify, or monitor in the next diagnosis

#### Scenario: Evidence grounding is included
- **WHEN** the report states a major insight or recurring gap
- **THEN** the report SHALL include supporting diagnosis report references or counts
- **AND** the report SHALL NOT claim a major pattern without supporting evidence

#### Scenario: Report output is validated
- **WHEN** the profile analysis agent returns a written report or structured report output
- **THEN** the system SHALL validate that recurring claims match validated clusters, cited evidence references exist, the requested subject is preserved, and one-report gaps are not labeled recurring

### Requirement: Mistake Pattern Analysis
The system SHALL analyze the nature of diagnosed mistakes, not only their chapter and topic.

#### Scenario: Mistake categories are identified
- **WHEN** profile evidence is analyzed
- **THEN** the system SHALL classify or summarize mistake patterns such as conceptual misunderstanding, incomplete concept coverage, formula or theorem misuse, prerequisite weakness, calculation or algebra error, question misreading, strategic avoidance, careless execution, or multi-concept integration failure when supported by evidence

#### Scenario: Intervention depends on mistake type
- **WHEN** the report recommends teacher intervention
- **THEN** the intervention notes SHALL reflect whether the evidence indicates reteaching, targeted drilling, prerequisite review, solving-process coaching, or monitoring for careless execution
