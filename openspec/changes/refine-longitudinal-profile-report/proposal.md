## Why

The current longitudinal profile pipeline finds semantically related diagnosis evidence, but its written reports do not consistently preserve the distinction between an exact recurring concept gap and a broader pattern connecting related-but-distinct gaps. This makes some findings too broad for students and teachers to act on and causes overlap between report sections.

## What Changes

- Define the overall report objective as producing objective, evidence-backed, actionable insights from concept-level gaps recurring across diagnosis reports.
- Give every report section a unique purpose, required content, exclusions, and measurable success criteria.
- Make the Overall Summary a concise decision summary of the strongest exact recurring gaps, broader patterns, evidence scope, and immediate student and teacher focus.
- Use two-stage semantic synthesis: first identify recurring concept gaps within a chapter/topic, then compare those gaps to identify the same type of conceptual reasoning gap across chapters/topics.
- Limit the written report to Overall Summary, Recurring Gaps, Broader Related Patterns, and an Evidence Appendix.
- Embed concise student and teacher actions within the relevant recurring-gap and broader-pattern entries instead of separate action sections.
- Prevent cross-chapter/topic patterns from being presented as one local recurring concept gap or duplicated across sections.
- Retain report-based recurrence: evidence from at least two distinct diagnosis reports is required for a recurring classification.
- Require the appendix to preserve the question analysis with test name, question number, subject, and test date.

## Capabilities

### New Capabilities

- `longitudinal-profile-report-quality`: Defines two-stage longitudinal synthesis, the restricted report structure, section responsibilities, evidence standards, and measurable quality criteria for student longitudinal profile reports.

### Modified Capabilities

None. The original `student-longitudinal-profile` capability remains in the completed but unarchived `build-student-longitudinal-profile` change; this follow-on capability refines the written-report contract without rewriting that completed change.

## Impact

- Semantic cluster classification prompts and validation.
- Longitudinal evidence-pack structure and chapter/topic mapping.
- Profile report prompts, structured output, validation, and deterministic fallback.
- Profile reporting tests and generated Markdown/PDF content.
