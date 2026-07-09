## ADDED Requirements

### Requirement: Vision Diagnosis Adapter Boundary
The system SHALL keep CrewAI and LiteLLM details behind vision diagnosis adapters.

#### Scenario: Vision diagnosis application runs
- **WHEN** the diagnosis workflow analyzes resolved images
- **THEN** batching, expected-question-number preservation, semantic retry decisions, and diagnosis validation SHALL be coordinated by application or domain code
- **AND** CrewAI tool classes and LiteLLM request construction SHALL remain adapter concerns

#### Scenario: CrewAI adapter invokes vision diagnosis
- **WHEN** CrewAI requests image analysis through the vision tool
- **THEN** the CrewAI adapter SHALL call the vision diagnosis application interface
- **AND** duplicate-call caching and failure replay behavior SHALL remain compatible with the existing vision tool execution requirements
