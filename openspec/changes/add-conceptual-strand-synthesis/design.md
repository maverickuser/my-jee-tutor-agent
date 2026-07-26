## Context

The current hierarchy moves directly from question evidence to an exact local gap constrained to one canonical chapter/topic pair. In the observed Physics profile, 26 diagnosed questions across six reports produced no recurring gap because related manifestations were distributed across topic labels. The renderer then emitted an empty summary and reproduced every diagnosis in the appendix.

The previous report generated useful synthesis but sometimes grouped evidence under generic labels such as formula recall, mathematical execution, or physical modeling. The replacement must recover synthesis without treating surface similarity or generic error behavior as a conceptual gap.

## Goals / Non-Goals

**Goals:**

- Represent a conceptual strand as one missing mental model or conceptual operation with multiple question manifestations.
- Validate recurrence using independent diagnosis reports rather than question count.
- Allow related topic labels within a chapter or closely related chapter-level concept family.
- Produce concise, prioritized, evidence-backed insights for students and teachers.
- Retain deterministic validation and rendering after semantic synthesis.
- Detect empty-insight regressions on evidence-rich representative fixtures.

**Non-Goals:**

- Reproduce question-level diagnosis reports.
- Guarantee that every evidence item belongs to a recurring conceptual strand.
- Label arithmetic slips, ambiguous questions, or generic carelessness as conceptual strands.
- Infer chronological improvement when authoritative test dates are unavailable.
- Restore the removed Study Priorities, Teacher Notes, or Chapter/Topic Map sections.

## Decisions

### 1. Replace exact local gaps with conceptual strands

A strand contains a precise missing mental model, its chapter-level concept family, related topics, distinct manifestations, one coherent corrective model, and supporting evidence IDs. The classifier must explain why the manifestations share a conceptual cause rather than only vocabulary.

Alternative considered: lower the embedding threshold while retaining exact chapter/topic grouping. This cannot connect evidence split across legitimate topic labels and would make similarity noise worse.

### 2. Generate chapter-family candidates before semantic adjudication

Local candidate generation groups evidence by normalized chapter family, not literal chapter/topic pair. Within a family, embedding-connected components provide candidates to a constrained classifier. The classifier can split candidates, exclude non-conceptual evidence, or produce a strand spanning multiple related topics.

Closely related chapter labels are normalized using deterministic token/alias rules so labels such as `Electrostatics` and `Electrostatics and Capacitance` can share a family without permitting arbitrary subject-wide local clusters.

### 3. Make manifestations first-class and auditable

Every evidence item in a strand maps to a short manifestation explaining how that question expresses the missing mental model. Validation requires exact coverage of the strand evidence IDs and rejects unknown, duplicate, or cross-family evidence.

This preserves specificity while allowing different question-level symptoms.

### 4. Validate recurrence after classification

A strand becomes reportable only when its evidence spans at least two diagnosis reports and its confidence is medium or high. Multiple questions from one paper strengthen evidence but do not establish longitudinal recurrence.

### 5. Separate conceptual strands from execution indicators

The local classifier returns both conceptual strands and excluded evidence classifications. Exclusion reasons include calculation execution, ambiguous/flawed question, insufficient evidence, and unrelated misconception. Exclusions remain available for audit but do not appear as recurring conceptual gaps.

### 6. Build broader patterns only from recurring strands

The broader classifier receives validated recurring strands, not raw question evidence. A broader pattern must connect at least two distinct chapter/concept families, name a common reasoning operation, retain each strand’s distinct manifestation, and identify one common corrective principle.

### 7. Make report content insight-led and compact

The deterministic renderer prioritizes strands by independent report count, evidence breadth, confidence, and actionability. Overall Summary names the highest-priority findings and interventions. Each recurring gap explains the missing model, manifestations across papers, student action, teacher intervention, and a verification check.

The appendix contains one compact row per evidence item with test/date, question, chapter/topic, diagnostic claim, and supported finding IDs. Full likely-reasoning and why-wrong prose remains in the source diagnosis artifact.

### 8. Add an evidence-rich minimum-insight quality gate

Production input can legitimately yield no insights, so runtime validation cannot require a non-empty report universally. Instead, a representative Physics-like regression fixture with capacitor-system and field-direction evidence across reports MUST produce the expected conceptual strands. This tests synthesis quality rather than document shape alone.

## Risks / Trade-offs

- [Risk] Chapter-family normalization may combine adjacent but distinct chapters. → Keep deterministic aliases narrow and require the semantic classifier to prove one corrective model covers all evidence.
- [Risk] A language model may generate plausible but unsupported causal explanations. → Require evidence-ID manifestations, constrained schemas, and deterministic coverage/context validation.
- [Risk] Broader candidates may become generic study-skill labels. → Reject patterns whose commonality is only formula recall, carelessness, vocabulary, or syllabus proximity.
- [Risk] Representative fixtures can overfit one student profile. → Test both positive Physics-like synthesis and negative unrelated/equivalent-vocabulary cases.
- [Trade-off] One additional semantic layer increases prompt size and classifier responsibility. → Keep two semantic calls: one subject-level conceptual-strand adjudication over local candidates and one optional broader-pattern call.

## Migration Plan

1. Replace local-gap models and classifier schema with conceptual-strand equivalents.
2. Update application orchestration and broader-pattern input.
3. Update deterministic report models and rendering while preserving the four section headings.
4. Add representative synthesis and negative-validation tests.
5. Deploy as a report-schema replacement because no external client consumes the current profile schema.
6. Roll back by reverting the runtime commit; stored diagnosis evidence remains compatible.

## Open Questions

- Authoritative test dates remain unavailable in current stored diagnoses; the report must continue to say so rather than treating diagnosis timestamps as test chronology.
