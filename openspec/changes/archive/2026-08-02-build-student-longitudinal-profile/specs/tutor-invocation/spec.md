## MODIFIED Requirements

### Requirement: Payload Validation

The system SHALL validate tutor invocations with a strict payload schema.

#### Scenario: Exactly one image source is provided

- **WHEN** the caller sends either `image_data_uri` or `image_s3_prefix`
- **THEN** the request is valid with respect to image source selection
- **AND** the system SHALL reject requests that provide both fields
- **AND** the system SHALL reject requests that provide neither field
- **AND** the system SHALL reject unknown payload fields

#### Scenario: Recipient email is provided

- **WHEN** `recipient_email` is present
- **THEN** the system SHALL trim and validate it as a non-blank email-like value
- **AND** the system SHALL require `image_s3_prefix`
- **AND** the system SHALL reject requests that request email with only `image_data_uri`

#### Scenario: Student and test metadata are encoded in the S3 path

- **WHEN** `image_s3_prefix` follows `users/{student_id}/{student_name}/tests/{test_name}/subjects/{subject}/questions/...`
- **THEN** the system SHALL parse `student_id`, `student_name`, `test_name`, and `subject` from the path
- **AND** the parsed metadata SHALL be used only for artifact paths, student diagnosis metadata, and profile analysis

#### Scenario: Safe trace input is emitted

- **WHEN** invocation input is passed to observability
- **THEN** the system SHALL omit `image_data_uri`
- **AND** the system SHALL omit `recipient_email`
- **AND** the system SHALL omit or redact parsed student metadata from S3 paths where logged

## ADDED Requirements

### Requirement: Student Diagnosis Report Capture
The invocation layer SHALL persist successful diagnosis output as a structured JSON report artifact and student diagnosis metadata.

#### Scenario: Diagnosis succeeds
- **WHEN** a diagnosis invocation includes `image_s3_prefix` with parseable student id, student name, test name, and subject segments
- **AND** the invocation includes `recipient_email`
- **AND** the CrewAI task-output guardrail approves structured diagnosis output
- **AND** the invocation reaches successful analysis response formatting
- **THEN** the system SHALL write the structured diagnosis JSON report beside the PDF artifact in S3
- **AND** the JSON artifact path SHALL preserve the parsed student id, student name, test name, and subject path segments
- **AND** the system SHALL write a student diagnosis metadata record containing parsed student id, recipient email, parsed student name, parsed subject, parsed test or paper name, diagnosis report id, diagnosis date, JSON report S3 path, PDF artifact S3 path when available, and number of questions analysed
- **AND** the existing single-attempt response shape SHALL remain compatible

#### Scenario: S3 metadata path is not parseable
- **WHEN** a diagnosis invocation uses `image_s3_prefix` but the path does not contain the required student/test/subject segments
- **THEN** the system SHALL continue the existing diagnosis flow
- **AND** the system SHALL NOT write student diagnosis metadata
- **AND** the system SHALL NOT publish a structured JSON report as profile evidence

#### Scenario: Diagnosis does not succeed
- **WHEN** payload validation, image resolution, input guardrail, task-output guardrail, workflow execution, or output guardrail handling prevents a successful diagnosis response
- **THEN** the system SHALL NOT write student diagnosis metadata
- **AND** the system SHALL NOT publish a structured JSON report as profile evidence

#### Scenario: Metadata storage is unavailable
- **WHEN** the diagnosis response succeeds but diagnosis metadata storage or JSON artifact writing is unavailable
- **THEN** the system SHALL report the storage failure in safe operational telemetry or response metadata according to configured policy
- **AND** the system SHALL record safe operational telemetry without exposing sensitive values
