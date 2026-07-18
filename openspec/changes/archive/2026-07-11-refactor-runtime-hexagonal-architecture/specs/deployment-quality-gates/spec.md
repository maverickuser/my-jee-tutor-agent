## ADDED Requirements

### Requirement: Refactor Quality Gates
The repository SHALL enforce quality gates that cover the refactored architecture.

#### Scenario: CI runs after the refactor
- **WHEN** CI executes static checks and tests
- **THEN** it SHALL include the refactored source layout
- **AND** it SHALL run architecture boundary, compatibility import, and representative invocation tests

#### Scenario: Runtime evaluation gates run after the refactor
- **WHEN** agent evaluations, deployed smoke tests, or optional security probes run
- **THEN** they SHALL use the same public handler path as before the refactor
- **AND** they SHALL validate behavior through the refactored composition path
