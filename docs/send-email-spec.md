# Send Email After Analysis

Status: Proposed

## Objective

Add a post-analysis email capability that sends the generated PDF to a single
recipient when the caller supplies `recipient_email`, using a fixed template
and a fixed subject configured by deployment settings.

The email feature must not replace the existing PDF artifact flow. The system
must still generate and store the PDF for every invocation that is configured
to produce artifacts, including when email delivery is disabled.

## Business Goal

The current workflow already generates a PDF analysis artifact. This feature
extends that workflow so an external caller can request an email delivery of
the same PDF without changing diagnosis behavior.

This is a delivery feature, not a new diagnosis feature.

## Scope

### In scope

- Add a `recipient_email` input field supplied by the external caller.
- Validate that email delivery is only attempted when the invocation is
  complete enough to produce a PDF.
- Send one email per invocation to one recipient.
- Attach the generated PDF to the email.
- Keep PDF generation and S3 persistence in place even when no recipient is
  provided.
- Use a fixed email template and a fixed configured subject.
- Surface a delivery state in the invocation response.
- Keep recipient data out of normal traces and logs.

### Out of scope

- CC, BCC, or multiple recipients.
- User-authored email body content.
- Custom subject lines from the caller.
- Changing the diagnosis output schema.
- Replacing S3 persistence with direct attachment-only storage.
- Choosing the async transport mechanism in this spec.

## Inputs

Add the following fields to the invocation payload:

```json
{
  "recipient_email": "student@example.com"
}
```

### Field rules

- `recipient_email` must be a valid email address when present.
- The external service invoking the agent supplies `recipient_email`.
- The model or agent does not invent recipient addresses.
- If `recipient_email` is absent, the request remains valid and no email is
  sent.

## PDF and Storage Contract

The PDF remains the source of truth for email delivery.

- The system must generate the PDF as part of the normal analysis artifact
  flow.
- The PDF must continue to be stored in S3 using the existing artifact path
  convention.
- The downstream email step must receive the S3 URI of the generated PDF.
- The email feature must not require a second PDF generation path.

This preserves reviewability and makes the email workflow a consumer of the
existing artifact.

## Delivery Contract

The email must be asynchronous from the invocation response.

Required business behavior:

1. The analysis pipeline completes.
2. The PDF is generated and stored.
3. If `recipient_email` is present, the system queues an email delivery
   request.
4. The invocation returns without waiting for delivery completion.
5. The caller can see whether email delivery was requested and queued.

### Delivery status

Return one of these states:

- `not_requested`
- `queued`
- `failed`

Use `not_requested` when `recipient_email` is absent.
Use `queued` when the email request was accepted for asynchronous processing.
Use `failed` when email queuing could not be completed.

If PDF generation succeeds but email queuing fails, the invocation should still
succeed overall and report the email failure separately.

## Email Content Contract

The email must be a fixed template.

### Required content

- Fixed subject configured in deployment settings.
- Fixed body template configured in deployment settings.
- The generated PDF attached to the email.

### Constraints

- Do not expose arbitrary free-form email text from the caller in v1.
- Do not include CC or BCC fields in v1.
- Do not make the attachment optional when `recipient_email` is present.
- Do not send a link-only email in v1.

## Configuration Contract

The sender identity and email template must be deployment configuration, not
caller input.

Recommended configuration inputs:

- `EMAIL_FROM_ADDRESS`
- `EMAIL_SUBJECT_TEMPLATE`
- `EMAIL_BODY_TEMPLATE`
- `EMAIL_REGION`

The spec does not choose the transport implementation. The downstream delivery
system may later be backed by SES, a queue, or another provider, but the
business contract must remain the same.

## Validation Rules

The invocation must fail validation when:

- `recipient_email` is present and invalid.
- `recipient_email` is present and no PDF can be produced.
- the request does not provide a supported artifact source for PDF generation.

The request remains valid when:

- `recipient_email` is omitted.
- PDF generation is required but email delivery is not.

## Response Contract

The response should continue to include the analysis and artifact fields.
Add an email delivery indicator so callers can see the request outcome.

Suggested fields:

- `email_status`
- `email_error`
- `analysis_pdf_uri`

The response must not imply delivery success at invoke time. It can only report
that the email was queued or that queueing failed.

## Idempotency Contract

Idempotent replay must not produce duplicate email requests.

For the same idempotency key:

- the PDF artifact should be reused or deterministically regenerated according
  to the existing artifact contract,
- the email request must be enqueued only once,
- repeated invocations should return the same email state whenever possible.

This is required for safe retries from the caller and platform.

## Observability and Privacy

Email delivery must be observable without leaking recipient data into general
logs or traces.

Requirements:

- redact or hash `recipient_email` in standard application traces,
- preserve enough metadata to debug delivery failures,
- avoid logging the full email body,
- treat recipient email as personal data.

## Business Flow

```text
Invocation received
  -> validate request
  -> run analysis
  -> generate PDF
  -> store PDF in S3
  -> if recipient_email is present, queue email delivery with recipient_email + PDF S3 URI
  -> return analysis + artifact metadata + email status
```

## Non-Goals

This feature does not:

- change how diagnosis is generated,
- change the PDF rendering format,
- introduce a second analysis artifact path,
- require synchronous email confirmation,
- support multiple recipients,
- support custom bodies or attachments beyond the PDF.

## Acceptance Criteria

The feature is complete when:

1. The invocation contract accepts `recipient_email`.
2. Email validation blocks invalid recipient addresses.
3. The system still writes the PDF even when no recipient is provided.
4. The email request uses a fixed template and fixed subject.
5. The email service receives the PDF S3 URI downstream.
6. The invocation returns asynchronously with a queued/failed/not_requested state.
7. Duplicate retries do not create duplicate email requests.
