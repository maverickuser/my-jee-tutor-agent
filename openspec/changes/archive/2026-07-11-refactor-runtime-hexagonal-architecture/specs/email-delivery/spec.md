## ADDED Requirements

### Requirement: Email Delivery Port Boundary
The system SHALL coordinate email delivery through explicit application and adapter boundaries.

#### Scenario: Email delivery is requested
- **WHEN** an invocation includes a recipient email and a stored PDF artifact is available
- **THEN** the invocation application SHALL use an email-delivery port to request delivery
- **AND** Lambda and SES implementation details SHALL remain inside email adapters
- **AND** delivery status, idempotency, and error behavior SHALL remain compatible with the existing email-delivery requirements
