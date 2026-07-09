## ADDED Requirements

### Requirement: Artifact Writer Port Boundary
The system SHALL persist analysis artifacts through an artifact-writer port.

#### Scenario: Artifact creation is requested
- **WHEN** the invocation application determines that a PDF or Markdown fallback artifact is required
- **THEN** it SHALL call an artifact-writer interface
- **AND** S3 upload, PDF rendering, URI derivation, and fallback details SHALL remain inside concrete artifact adapters
- **AND** artifact response fields SHALL remain compatible with the existing artifact requirements
