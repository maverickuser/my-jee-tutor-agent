# Email Delivery Specification

## Purpose

Defines the asynchronous email delivery path for generated analysis PDFs.

## Requirements

### Requirement: Email Request Eligibility

The system SHALL request email delivery only for valid invocations that can produce a stored PDF artifact.

#### Scenario: Recipient email is absent

- **WHEN** `recipient_email` is absent
- **THEN** the invocation response SHALL report `email_status` as `not_requested`
- **AND** no email delivery request SHALL be queued

#### Scenario: Recipient email is present

- **WHEN** `recipient_email` is present
- **THEN** the payload SHALL require `image_s3_prefix`
- **AND** the invocation SHALL attempt to create a PDF artifact before queuing email delivery

#### Scenario: PDF artifact is unavailable

- **WHEN** `recipient_email` is present
- **AND** no `analysis_pdf_uri` is available
- **THEN** the invocation SHALL continue to return the analysis response
- **AND** report `email_status` as `failed`
- **AND** report an email error explaining that email requires a stored PDF artifact

### Requirement: Email Delivery Coordination

The system SHALL queue email delivery through an asynchronous Lambda invocation.

#### Scenario: Delivery configuration is invalid

- **WHEN** delivery configuration validation fails
- **THEN** the coordinator SHALL return `failed`
- **AND** include the validation error text

#### Scenario: Delivery is accepted

- **WHEN** delivery configuration is valid
- **AND** Lambda accepts the asynchronous event with status 200 or 202
- **AND** no Lambda function error is reported
- **THEN** the coordinator SHALL return `queued`
- **AND** include a deterministic `delivery_id`

#### Scenario: Lambda invocation fails

- **WHEN** Lambda invocation raises an exception, reports `FunctionError`, or returns an unexpected status
- **THEN** the coordinator SHALL return `failed`
- **AND** include the delivery id and a compact error string

### Requirement: Email Delivery Idempotency

The system SHALL suppress duplicate email delivery requests within the coordinator process.

#### Scenario: Delivery id is generated

- **WHEN** a delivery request is prepared
- **THEN** the delivery id SHALL be a SHA-256 hash of the idempotency key if present, normalized recipient email, and PDF URI

#### Scenario: Duplicate delivery request

- **WHEN** a delivery request repeats an existing delivery id
- **THEN** the coordinator SHALL return the previously stored outcome
- **AND** SHALL NOT invoke Lambda a second time

### Requirement: Email Worker

The system SHALL send queued PDF emails from the worker.

#### Scenario: Worker receives invalid event

- **WHEN** the worker event fails validation
- **THEN** the worker SHALL return `failed`
- **AND** include `Invalid email delivery event.`

#### Scenario: Worker receives duplicate delivery id

- **WHEN** the worker has already processed the delivery id
- **THEN** it SHALL return the stored outcome
- **AND** SHALL NOT fetch the PDF or send another email

#### Scenario: Worker sends email

- **WHEN** the worker receives a valid event and valid configuration
- **THEN** it SHALL load the PDF bytes from the event PDF S3 URI
- **AND** render the configured subject and body templates
- **AND** send one SES email to the event recipient with the PDF attached
- **AND** return `succeeded` with the delivery id

#### Scenario: Worker fails

- **WHEN** configuration validation, PDF fetch, template rendering, or SES sending fails
- **THEN** the worker SHALL return `failed`
- **AND** include the delivery id and compact error string
