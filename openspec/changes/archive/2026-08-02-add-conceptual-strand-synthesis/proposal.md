## Why

The deployed longitudinal profile can contain dozens of diagnosed mistakes across several papers yet report that no insight exists. Requiring near-identical question diagnoses within an exact chapter/topic label removed the synthesis layer that teachers and students need: a defensible conceptual strand connecting different manifestations of one missing mental model.

## What Changes

- Introduce a conceptual-strand layer between question evidence and reportable recurring gaps.
- Permit a recurring strand to connect different topic labels within one chapter or closely related chapter-level concept family when one coherent corrective intervention addresses every manifestation.
- Require recurrence across at least two independent diagnosis reports and preserve evidence-to-strand traceability.
- Separate exact repeated misconceptions, related manifestations of one conceptual strand, and non-conceptual execution indicators.
- Build broader related patterns only from validated recurring strands spanning distinct chapter/concept contexts.
- Make the overall summary synthesize and prioritize actual findings instead of emitting generic evidence counts.
- Replace the full question-diagnosis appendix dump with compact evidence rows mapped to the findings they support.
- Add regression fixtures based on the observed Physics profile so evidence-rich input cannot silently degrade into an empty-insight report.

## Capabilities

### New Capabilities

- `longitudinal-conceptual-strand-synthesis`: Defines conceptual-strand formation, cross-paper validation, insight prioritization, broader-pattern synthesis, compact evidence traceability, and minimum insight-quality behavior.

### Modified Capabilities

None.

## Impact

- Affects the profile hierarchy models, semantic classifier contracts and prompts, application orchestration, deterministic report builder, Markdown/PDF output, and profile tests.
- Replaces the exact chapter/topic local-gap contract introduced by `refine-longitudinal-profile-report`.
- Keeps the four agreed report sections and existing artifact delivery interface.
- Does not restore question-level diagnosis prose as report content.
