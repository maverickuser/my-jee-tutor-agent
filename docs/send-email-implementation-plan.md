# Send Email After Analysis Implementation Plan

Status: Proposed

Source docs:

- [`send-email-spec.md`](send-email-spec.md)
- [`send-email-hld.md`](send-email-hld.md)
- [`send-email-lld.md`](send-email-lld.md)

## Goal

Implement asynchronous post-analysis email delivery with these constraints:

- only send when `recipient_email` is present,
- always keep PDF generation and S3 storage in place,
- invoke Lambda asynchronously,
- send through SES inside the worker,
- preserve idempotency and safe logging.

## Phase 1: Data Contract

Files:

- `src/jee_tutor/invocation/models.py`
- `src/jee_tutor/invocation/service.py`
- tests under `tests/invocation/`

Changes:

- add `recipient_email` to `TutorInvocationPayload`,
- validate email format when present,
- add response fields for email state,
- keep existing no-recipient behavior unchanged.

Exit criteria:

- old payloads still succeed,
- payloads with valid recipient email validate,
- invalid recipient email fails fast.

## Phase 2: Runtime Email Coordinator

Files:

- `src/jee_tutor/email/delivery.py`
- `src/jee_tutor/email/config.py`
- `src/jee_tutor/email/models.py`
- tests under `tests/email/`

Changes:

- add `EmailDeliveryRequest`,
- add `EmailDeliveryOutcome`,
- implement `EmailDeliveryCoordinator`,
- derive stable `delivery_id`,
- map async invoke success/failure to outcome states,
- keep recipient email out of logs.

Exit criteria:

- coordinator returns `queued`, `failed`, or `not_requested`,
- duplicate requests are suppressed by `delivery_id`,
- runtime can create a delivery request without touching SES directly.

## Phase 3: Lambda Worker

Files:

- `src/jee_tutor/email/worker.py`
- `src/jee_tutor/email/ses_adapter.py`
- `src/jee_tutor/email/templates.py`
- Lambda entrypoint wrapper if needed

Changes:

- accept the delivery event,
- validate payload,
- load PDF bytes from S3,
- render fixed body template,
- attach PDF,
- call SES,
- persist worker outcome,
- make the worker idempotent on `delivery_id`.

Exit criteria:

- worker sends a valid email with attachment,
- duplicate events do not send twice,
- worker failures are classified as transient or terminal.

## Phase 4: Invocation Wiring

Files:

- `src/jee_tutor/invocation/service.py`
- `src/jee_tutor/artifacts/writer.py`
- possibly `src/jee_tutor/app.py` or runtime bootstrap files

Changes:

- after analysis succeeds, always write the PDF as before,
- if `recipient_email` exists, call the coordinator,
- preserve the current artifact response shape,
- extend the response with email state.

Exit criteria:

- invocation without recipient keeps current behavior,
- invocation with recipient triggers async email request,
- PDF artifact URI is reused by the worker path.

## Phase 5: Observability

Files:

- `src/jee_tutor/email/delivery.py`
- `src/jee_tutor/email/worker.py`
- `src/jee_tutor/email/config.py`
- observability helpers if needed

Changes:

- add structured logs for request, async invoke, worker success/failure,
- add metrics for request, invoke, duplicate suppression, retries, failures,
- redact recipient email in all default traces.

Exit criteria:

- logs are bounded and structured,
- metrics separate runtime and worker paths,
- no plaintext recipient email in standard logs.

## Phase 6: Deployment Surface

Files:

- runtime bootstrap files
- Lambda deployment files
- Terraform if the Lambda is provisioned here

Changes:

- add env vars for sender/template/provider/function ARN,
- add permissions for async Lambda invocation,
- add permissions for S3 read and SES send in the worker role.

Expected env vars:

- `EMAIL_FROM_ADDRESS=Koncept Agent App <sociusnest@gmail.com>`
- `EMAIL_SUBJECT_TEMPLATE=Analysis Report`
- `EMAIL_BODY_TEMPLATE=<HTML template>`
- `EMAIL_REGION=<AWS region>`
- `EMAIL_DELIVERY_PROVIDER=lambda`
- `EMAIL_DELIVERY_FUNCTION_ARN=<provisioned Lambda ARN>`

Exit criteria:

- runtime can invoke the worker Lambda,
- worker can read PDF artifacts from S3,
- worker can call SES.

## Phase 7: Tests

### Runtime tests

- validate optional recipient email,
- no-recipient path returns `not_requested`,
- recipient path invokes coordinator,
- PDF write failure blocks email request,
- async invoke failure returns `failed`.

### Worker tests

- validate delivery event,
- fetch PDF from S3 URI,
- render fixed template,
- send SES attachment,
- suppress duplicate `delivery_id`.

### Integration tests

- invocation with recipient creates email request,
- invocation without recipient remains unchanged,
- replay with same idempotency key does not duplicate email.

## Suggested Order

1. Add models and validation.
2. Add runtime coordinator.
3. Add worker and SES adapter.
4. Wire coordinator into invocation service.
5. Add logs and metrics.
6. Add deployment permissions and env vars.
7. Add tests and verify end-to-end flow.

## Definition of Done

- Email only sends when `recipient_email` is present.
- The PDF artifact path remains unchanged.
- Lambda async invoke is idempotent at the delivery key level.
- Worker is retry-safe and duplicate-safe.
- Logs and metrics are clean and bounded.
