## MODIFIED Requirements

### Requirement: Payload Validation

The system SHALL validate tutor invocations with a strict payload schema.

#### Scenario: Exactly one image source is provided

- **WHEN** the caller sends a diagnosis invocation with either `image_data_uri` or `image_s3_prefix`
- **THEN** the request is valid with respect to image source selection
- **AND** the system SHALL reject requests that provide both fields
- **AND** the system SHALL reject requests that provide neither field
- **AND** the system SHALL reject unknown payload fields

#### Scenario: Profile task does not require image source

- **WHEN** the caller sends `task` equal to `profile` or a supported profile-task alias after normalization
- **THEN** payload validation SHALL NOT require `image_data_uri` or `image_s3_prefix`
- **AND** the request SHALL be routed to the actionable-insights replacement for the student profile task
- **AND** the replacement SHALL use structured diagnosis JSON and compatible cached embeddings for the requested student and subject
- **AND** diagnosis image-source validation SHALL remain unchanged for non-profile tasks

#### Scenario: Recipient email is provided

- **WHEN** `recipient_email` is present for a diagnosis invocation
- **THEN** the system SHALL trim and validate it as a non-blank email-like value
- **AND** the system SHALL require `image_s3_prefix`
- **AND** the system SHALL reject requests that request email with only `image_data_uri`

#### Scenario: Safe trace input is emitted

- **WHEN** invocation input is passed to observability
- **THEN** the system SHALL omit `image_data_uri`
- **AND** the system SHALL omit `recipient_email`
