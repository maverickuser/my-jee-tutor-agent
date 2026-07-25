## 1. Evidence and Models

- [x] 1.1 Add nullable test-date metadata/evidence support and keep diagnosis date distinct.
- [x] 1.2 Add normalized chapter/topic context and structured local-gap, broader-pattern, and hierarchical evidence-pack models.

## 2. Two-Stage Analysis

- [x] 2.1 Implement chapter/topic-scoped local candidate classification with auditable exact-gap output and report-based recurrence.
- [x] 2.2 Implement cross-context candidate analysis over recurring local gaps with component-gap validation.
- [x] 2.3 Wire the application service to build the hierarchical evidence pack through both stages.

## 3. Report Replacement

- [x] 3.1 Replace the report output schema with Overall Summary, Recurring Gaps, Broader Related Patterns, and Evidence Appendix.
- [x] 3.2 Implement deterministic summary selection, finding actions, appendix construction, validation, and Markdown rendering.
- [x] 3.3 Remove legacy report-writer orchestration and obsolete report sections.

## 4. Verification

- [x] 4.1 Update semantic, evidence, reporting, application, artifact, and smoke tests for the replacement schema.
- [x] 4.2 Add tests proving local scope, cross-context hierarchy, report-count recurrence, test-date handling, and unsupported-pattern rejection.
- [x] 4.3 Run OpenSpec validation, unit tests, coverage, and Ruff.
