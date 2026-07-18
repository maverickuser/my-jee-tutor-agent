# Analysis Artifacts Specification

## Purpose

Defines how tutor analysis output is persisted as invocation artifacts.
## Requirements
### Requirement: Artifact Creation Decision

The system SHALL decide whether to create analysis artifacts from the invocation payload.

#### Scenario: PDF saving is enabled

- **WHEN** `save_analysis_pdf` is true
- **THEN** the system SHALL attempt to write analysis artifacts after successful workflow analysis

#### Scenario: Email is requested

- **WHEN** `recipient_email` is present
- **THEN** the system SHALL attempt to write analysis artifacts even if `save_analysis_pdf` is false

#### Scenario: Direct image input without email

- **WHEN** only `image_data_uri` is provided
- **AND** no email is requested
- **THEN** artifact writing SHALL produce no S3 artifact URI because no S3 prefix is available

### Requirement: PDF Artifact Location

The system SHALL derive the PDF artifact URI from the invocation S3 image prefix.

#### Scenario: Subject is provided

- **WHEN** `image_s3_prefix` and `subject` are provided
- **THEN** the PDF SHALL be written under the image prefix
- **AND** the filename SHALL be `<sanitized-subject>_analysis.pdf`

#### Scenario: Subject is absent or sanitizes to blank

- **WHEN** no usable subject is available
- **THEN** the PDF filename SHALL be `analysis.pdf`

#### Scenario: Subject contains unsafe filename characters

- **WHEN** the subject contains characters outside letters, numbers, dot, underscore, or hyphen
- **THEN** those runs SHALL be replaced with underscores
- **AND** leading or trailing dot, underscore, and hyphen characters SHALL be stripped

### Requirement: PDF Rendering and Upload

The system SHALL render analysis Markdown into a PDF and upload it to S3.

#### Scenario: PDF render and upload succeeds

- **WHEN** PDF rendering and S3 upload succeed
- **THEN** the response SHALL include `analysis_pdf_uri`
- **AND** include a wait message for the PDF
- **AND** include `pdf_wait_minutes` equal to 5

#### Scenario: PDF render or upload fails

- **WHEN** PDF rendering or upload fails
- **THEN** the invocation SHALL still return the analysis response
- **AND** the response SHALL include an artifact error describing the PDF failure
- **AND** the system SHALL attempt to write a Markdown fallback artifact

#### Scenario: Analysis contains taxonomy review markers

- **WHEN** analysis Markdown contains chapter or topic labels marked with `[Needs human validation]`
- **THEN** the PDF and Markdown artifacts SHALL preserve those markers in the relevant table cells
- **AND** the artifacts SHALL include a disclaimer stating that marked chapter/topic labels were not found in the approved curriculum taxonomy and should be validated by a human

### Requirement: Markdown Fallback Artifact

The system SHALL persist a Markdown fallback when PDF artifact creation fails.

#### Scenario: Markdown fallback succeeds

- **WHEN** PDF artifact creation fails
- **AND** Markdown upload succeeds
- **THEN** the response SHALL include `analysis_markdown_uri`
- **AND** SHALL include the PDF artifact error

#### Scenario: Markdown fallback fails

- **WHEN** both PDF artifact creation and Markdown fallback upload fail
- **THEN** the response SHALL include artifact errors for both failures
- **AND** the invocation SHALL still return the analysis text

### Requirement: Artifact Writer Port Boundary
The system SHALL persist analysis artifacts through an artifact-writer port.

#### Scenario: Artifact creation is requested
- **WHEN** the invocation application determines that a PDF or Markdown fallback artifact is required
- **THEN** it SHALL call an artifact-writer interface
- **AND** S3 upload, PDF rendering, URI derivation, and fallback details SHALL remain inside concrete artifact adapters
- **AND** artifact response fields SHALL remain compatible with the existing artifact requirements
