# Send Email After Analysis LLD

Status: Proposed

Source HLD:
[`send-email-hld.md`](send-email-hld.md)

## Purpose

Define the code-level design for the post-analysis email path:

- generate the PDF as part of the existing invocation flow,
- persist the PDF in S3,
- asynchronously invoke a Lambda worker when `recipient_email` is present,
- have the worker load the PDF and send it through SES,
- keep the path idempotent and observable.

## Implementation Boundaries

### Runtime side

Owns:

- request validation,
- diagnosis workflow execution,
- PDF artifact creation,
- email request creation,
- async Lambda invocation,
- response shaping.

### Worker side

Owns:

- async event handling,
- S3 PDF fetch,
- fixed template rendering,
- SES send,
- delivery result persistence,
- retry-safe idempotent execution.

## Proposed Modules

### Runtime modules

- `src/jee_tutor/invocation/models.py`
- `src/jee_tutor/invocation/service.py`
- `src/jee_tutor/artifacts/writer.py`
- `src/jee_tutor/email/delivery.py`
- `src/jee_tutor/email/config.py`
- `src/jee_tutor/email/models.py`

### Worker modules

- `src/jee_tutor/email/worker.py`
- `src/jee_tutor/email/ses_adapter.py`
- `src/jee_tutor/email/templates.py`

If the repository prefers a top-level entrypoint for the Lambda package, add a
thin wrapper such as `src/email_delivery_handler.py` that delegates to
`jee_tutor.email.worker`.

## Runtime Data Flow

```text
TutorInvocationService.handle
  -> TutorInvocationPayload validation
  -> image resolution
  -> guardrail + analysis workflow
  -> AnalysisArtifactWriter.write_for_invocation
  -> if recipient_email present:
       -> EmailDeliveryCoordinator.request_delivery
       -> Lambda client async invoke
  -> response with analysis + artifact fields + email_status
```

## Data Models

### Invocation payload

Add `recipient_email: str | None` to `TutorInvocationPayload`.

Validation rules:

- optional field,
- if present, validate as email,
- if absent, no email request is created.

### Email delivery request

Internal request object should be separate from the public payload.

Suggested fields:

```python
class EmailDeliveryRequest(BaseModel):
    recipient_email: str
    pdf_uri: str
    invocation_id: str | None
    idempotency_key: str | None
    subject_key: str
    body_template_key: str
    from_address_key: str
```

Do not persist image data or analysis text in this object.

### Delivery outcome

```python
class EmailDeliveryStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    QUEUED = "queued"
    FAILED = "failed"


class EmailDeliveryOutcome(BaseModel):
    status: EmailDeliveryStatus
    delivery_id: str | None = None
    error: str | None = None
```

## Runtime Call Flow

1. Validate the invocation payload.
2. Resolve input images.
3. Run the existing diagnosis workflow.
4. Write the PDF to S3 using the existing artifact writer.
5. If `recipient_email` is absent, return success with `email_status=not_requested`.
6. If `recipient_email` is present, build an `EmailDeliveryRequest`.
7. Invoke the Lambda worker asynchronously with the request payload.
8. Map Lambda acceptance to `email_status=queued`.
9. Map async invoke failure to `email_status=failed`.

## Coordinator Design

`EmailDeliveryCoordinator` should be a small service class that owns:

- request normalization,
- delivery key derivation,
- idempotency check,
- async Lambda invocation,
- safe error mapping.

Suggested interface:

```python
class EmailDeliveryCoordinator(Protocol):
    def request_delivery(
        self,
        *,
        recipient_email: str,
        pdf_uri: str,
        invocation_id: str | None,
        idempotency_key: str | None,
    ) -> EmailDeliveryOutcome: ...
```

### Delivery key

Use a stable key derived from:

- `idempotency_key`
- `recipient_email`
- `pdf_uri`

Store or memoize the key before invoking Lambda so duplicate runtime retries do
not create duplicate sends.

## Worker Design

### Worker entrypoint

The Lambda handler should accept a small JSON event:

```python
class EmailDeliveryEvent(BaseModel):
    delivery_id: str
    recipient_email: str
    pdf_uri: str
    subject_key: str
    body_template_key: str
    from_address_key: str
```

### Worker steps

1. Validate the event.
2. Load the PDF bytes from S3 using `pdf_uri`.
3. Resolve fixed sender and template config.
4. Render the email body from the configured template.
5. Attach the PDF.
6. Send via SES.
7. Persist success or failure metadata.

### Worker idempotency

The worker must treat `delivery_id` as the idempotency boundary.

Behavior:

- if a completed `delivery_id` is seen again, no-op,
- if a running `delivery_id` is seen again, return the same in-flight state or
  fail closed,
- if SES send already succeeded, do not send a second email.

## Failure Mapping

### Runtime side

- invalid `recipient_email` -> validation error
- PDF write failure -> normal artifact error path, no email request
- async invoke failure -> `email_status=failed`

### Worker side

- invalid event -> terminal failure
- missing PDF in S3 -> terminal failure or bounded retry, depending on policy
- SES transient failure -> retryable failure
- SES permanent failure -> terminal failure

## Logging

Use structured logs only.

Runtime logs should include:

- `delivery_id`
- `invocation_id`
- `analysis_pdf_uri`
- `email_status`
- sanitized error class

Worker logs should include:

- `delivery_id`
- `pdf_uri`
- `worker_status`
- sanitized provider error class

Never log:

- recipient email in plaintext,
- PDF bytes,
- full email body,
- raw SES response payloads.

## Metrics

Recommended counters:

- `email_delivery_requested_count`
- `email_delivery_invoked_count`
- `email_delivery_failed_count`
- `email_delivery_succeeded_count`
- `email_delivery_duplicate_suppressed_count`
- `email_delivery_validation_failed_count`
- `email_delivery_async_invoke_retry_count`
- `email_delivery_provider_retry_count`
- `email_pdf_fetch_failed_count`

Recommended dimensions:

- `path=runtime|worker`
- `result=queued|failed|not_requested|succeeded`
- `failure_type=validation|async_invoke|pdf_fetch|provider|duplicate`

## Configuration

The runtime and worker should read these environment variables:

- `EMAIL_FROM_ADDRESS` default: `analysis@konceptai.com`
- `EMAIL_SUBJECT_TEMPLATE` default: `Test Analysis Report`
- `EMAIL_BODY_TEMPLATE` default: HTML analysis email template with `{delivery_id}`
- `EMAIL_REGION` default: deployment AWS region
- `EMAIL_DELIVERY_PROVIDER` default: `lambda`
- `EMAIL_DELIVERY_FUNCTION_ARN` default: the provisioned email Lambda ARN

Recommended env vars:

- `EMAIL_FROM_ADDRESS`
- `EMAIL_SUBJECT_TEMPLATE`
- `EMAIL_BODY_TEMPLATE`
- `EMAIL_REGION`
- `EMAIL_DELIVERY_PROVIDER`
- `EMAIL_DELIVERY_FUNCTION_ARN`

## Testing

### Runtime tests

- payload without `recipient_email` returns `not_requested`
- payload with valid `recipient_email` invokes coordinator
- invalid `recipient_email` fails validation
- PDF write failure prevents email request
- async invoke failure maps to `failed`

### Worker tests

- validates event payload
- loads PDF bytes from S3 URI
- sends SES message with attachment
- no-ops on duplicate `delivery_id`
- handles transient and terminal SES failures separately

### Integration tests

- end-to-end invocation with recipient writes PDF and emits async invoke
- invocation without recipient keeps existing artifact behavior
- idempotent replay does not duplicate email requests
