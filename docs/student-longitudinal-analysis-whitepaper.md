# Student Longitudinal Diagnosis Analysis

## Executive Summary

Today, the tutor agent produces a diagnosis report for a single student attempt. That report is useful for understanding what went wrong in one paper or one set of incorrect questions, but it does not answer a deeper learning question: what patterns keep repeating across the student's attempts?

The longitudinal diagnosis analysis capability aims to transform multiple diagnosis reports into a subject-level learning profile for a student. The profile should help the student understand what to fix next and help the teacher understand what to reteach, drill, or monitor.

The core idea is to move from isolated mistake diagnosis to evidence-backed learning pattern analysis.

## Problem Statement

Students and teachers often see mistakes as scattered across tests, chapters, and questions. A student may receive several diagnosis reports over time, each explaining a few wrong questions. However, the real learning value often lies across reports:

- the same conceptual misunderstanding appearing in different questions
- the same wrong approach appearing in different topics
- a recurring inability to apply a law under changed conditions
- confusion between formula recall and conceptual applicability
- repeated use of shortcuts where first-principles setup is required

A single report can say, "this question went wrong because of this gap." A longitudinal profile should say, "these repeated gaps reveal this underlying learning pattern."

The product problem is therefore:

> How can we convert multiple per-attempt diagnosis reports into a reliable, evidence-backed student learning profile that identifies recurring gaps, related mistake patterns, and practical next actions for both student and teacher?

## Users And Value

### Student Value

The student needs clarity and prioritization. The report should reduce the feeling that mistakes are random and should answer:

- What are my recurring weaknesses in this subject?
- Which mistakes are isolated and which are repeated?
- What exact concept or approach should I fix first?
- What should I revise and practice next?
- What should I consciously check while solving future questions?

For the student, the value is turning "I got many questions wrong" into "I understand the repeated learning mechanism behind my mistakes."

### Teacher Value

The teacher needs intervention guidance. The report should answer:

- Which concepts or approaches repeatedly break down?
- Which chapter/topic areas are affected?
- Is the issue conceptual, procedural, strategic, or execution-related?
- What should be retaught?
- What should be drilled?
- What should be monitored in the next diagnosis?

For the teacher, the value is turning "the student is weak in this chapter" into "this is the exact intervention needed."

## Why Single Diagnosis Reports Are Not Enough

Single reports are intentionally scoped to the current attempt. They diagnose the visible evidence from current wrong or unattempted questions. That is the right behavior for immediate diagnosis, but it misses longitudinal signals.

For example, two reports may contain different wording:

- "Did not check left-hand and right-hand limits before claiming continuity."
- "Assumed direct substitution proves continuity in a piecewise function."
- "Confused function value with the limiting value."

These are not identical text strings, but they may represent the same deeper learning issue: the student treats continuity as substitution rather than a three-condition check.

Similarly, in Physics, two electromagnetic induction mistakes may not be the same exact concept gap, but they may reveal a broader fragile pattern in induction reasoning:

- misunderstanding induced electric field geometry
- confusing magnetic flux with rate of change of flux

The longitudinal system must therefore reason beyond exact text matching while staying grounded in actual diagnosis evidence.

## Proposed Solution

The proposed solution is a requested, per-subject longitudinal profile report generated from a student's historical diagnosis reports.

At a high level:

```text
Diagnosis Reports
        |
        v
Structured Learning Evidence
        |
        v
Semantic Gap Analysis
        |
        v
Longitudinal Evidence Pack
        |
        v
Student + Teacher Profile Report
```

The profile report should not simply concatenate old reports. It should identify patterns across them and explain what those patterns mean.

## Core Principles

### Evidence First

Every major insight must be traceable to actual diagnosis evidence. The profile should cite supporting report/question references or supporting report counts.

### Per-Subject Scope

The first version should analyze one subject at a time. Cross-subject profiling can be valuable later, but per-subject analysis keeps the report focused and easier to validate.

### Requested Generation

The profile should be generated when requested by the student or teacher, not automatically after every diagnosis.

### Explicit Student Identity

The system should use a clear student identity, such as student email, to link reports over time. Because email is personally identifiable information, the system should treat it carefully and avoid unnecessary exposure in prompts, logs, and reports.

### Separate Diagnosis And Profile Analysis

The existing diagnosis agent should continue to diagnose only the current attempt. A separate profile analysis flow should analyze historical evidence. This keeps immediate diagnosis evidence-grounded and prevents past mistakes from biasing current-question diagnosis.

### Semantic Clustering With Guardrails

Exact string matching is not enough to identify repeated learning gaps. The system should use semantic analysis to identify when different wording points to the same underlying concept gap or similar wrong approach.

However, semantic analysis should operate over controlled evidence items, not raw unbounded history. The system should preserve evidence references and validate claims after analysis.

## Longitudinal Analysis Method

### 1. Collect Structured Evidence

Each successful diagnosis should produce a structured JSON diagnosis report in addition to human-readable artifacts such as PDF or Markdown.

The system should also maintain a student diagnosis metadata record in a database. This metadata record is the index that lets the profile system find the right historical diagnosis reports without parsing PDFs or scanning storage paths.

At the report level, the metadata should include:

- student id, using the student's email identity
- subject
- test or paper name
- diagnosis report id
- diagnosis date
- S3 path of the structured JSON diagnosis report
- optional S3 paths for human-readable artifacts such as PDF or Markdown

The structured JSON diagnosis report should contain the question-level learning evidence. Each evidence item corresponds to one diagnosed question and should include:

- diagnosis report id
- question number
- chapter
- topic
- what the student likely thought
- why that thought was wrong
- exact concept gap
- what the student must deep-dive

This creates two complementary layers:

```text
Metadata database
  -> who, subject, test name, date, JSON report S3 path

Structured JSON diagnosis report
  -> question-level diagnosis rows used for longitudinal analysis
```

The profile system should not depend on parsing PDF reports. PDF and Markdown are presentation formats; longitudinal analysis should load structured JSON reports referenced by the metadata records.

### 2. Prepare Evidence For Analysis

When a profile report is requested, the system gathers evidence for the requested student and subject.

This stage establishes the boundaries of analysis:

- only this student
- only this subject
- only stored diagnosis evidence
- no image payloads
- no unrelated report history

### 3. Identify Semantic Gap Clusters

This is the most important analytical step.

The system should group diagnosis evidence by semantic similarity, using columns such as:

- exact concept gap
- why the thought is wrong
- what the student thought
- what the student must deep-dive
- chapter and topic as context

Chapter and topic explain where the mistake happened. The concept-gap and reasoning columns explain what actually broke.

The semantic analysis should distinguish:

- same underlying concept gap
- same wrong approach
- same prerequisite weakness
- same execution pattern
- related but distinct subgaps
- unrelated mistakes in the same chapter/topic

For example:

```text
Report A:
Misunderstanding geometry of non-conservative induced electric field.

Report B:
Misapplication of Faraday's law by confusing flux with rate of change of flux.
```

These should not be merged as the same exact gap. They may instead be marked as related subgaps under a broader electromagnetic induction reasoning weakness.

### 4. Compute Recurrence From Evidence

After semantic grouping, recurrence should be based on supporting diagnosis reports.

A gap or pattern should be called recurring only if it is supported by evidence from at least two separate diagnosis reports.

Multiple questions in the same report can increase severity, but they should not alone prove recurrence.

This distinction matters because the product is about long-term learning patterns, not one-session density.

### 5. Build A Longitudinal Evidence Pack

Before writing the final report, the system should create an evidence pack containing:

- total diagnosis report count
- total diagnosed question count
- recurring gaps
- isolated or early-indicator gaps
- broader related patterns
- chapter/topic map
- evidence references
- suggested student focus areas
- suggested teacher intervention themes

The evidence pack becomes the source of truth for the profile report.

### 6. Generate The Written Profile Report

The profile report should explain the evidence in language useful to both student and teacher.

Recommended sections:

- overall summary
- recurring gaps
- related broader learning patterns
- chapter/topic weakness map
- isolated or early-indicator gaps
- recommended study priorities
- teacher intervention notes
- evidence appendix

The report should be written, not just a graph. A graph can become a future UI layer, but the first value is interpretation.

## Example Analysis Pattern

From two Physics diagnosis reports, suppose the visible evidence contains:

```text
Paper 1, Question 3:
Chapter: Electromagnetic Induction
Topic: Induced Electric Field
Gap: Misunderstanding the geometry of the non-conservative induced electric field.

Paper 2, Question 3:
Chapter: Electromagnetic Induction
Topic: Faraday's Law of Induction
Gap: Misapplication of Faraday's Law by confusing magnetic flux with its time derivative.
```

A weak analysis would simply say:

```text
Electromagnetic Induction: 2 mistakes
```

A better longitudinal analysis would say:

```text
There is a recurring broader weakness in electromagnetic induction reasoning across two reports.
The exact subgaps are different:
- induced electric field geometry and direction
- rate-of-change interpretation in Faraday's law

This suggests the student may know EMI formulas but struggles to connect them to field geometry and changing-flux reasoning.
```

This is the kind of synthesis the profile system should produce.

## What The Report Should Avoid

The profile report should not:

- merely concatenate old diagnosis rows
- call a one-report issue recurring
- group mistakes only because they share a chapter
- merge distinct subgaps as the same exact gap
- invent chapters, topics, or evidence
- provide generic advice such as "practice more"
- expose raw student email, image payloads, or model internals

## Success Criteria

The longitudinal analysis capability is successful if:

- a student can understand their most important repeated learning gaps
- a teacher can identify what to reteach, drill, or monitor
- every major claim is backed by diagnosis evidence
- exact recurring gaps are separated from broader related patterns
- one-report gaps are treated as early indicators, not persistent weaknesses
- profile reports are generated per subject when requested
- structured diagnosis evidence supports future analysis without relying on PDF parsing

## High-Level Plan

1. Ensure each diagnosis report produces structured learning evidence.
2. Link diagnosis reports to a student identity and subject.
3. Add a separate profile analysis flow that can be requested by student and subject.
4. Use semantic analysis to cluster related concept gaps and wrong approaches.
5. Compute recurrence from distinct diagnosis report evidence.
6. Build a longitudinal evidence pack.
7. Generate a written student and teacher profile report from that evidence pack.
8. Validate that major claims are evidence-backed and recurrence rules are respected.

## Future Directions

Future versions can extend this foundation with:

- visual mistake graphs
- cross-subject patterns
- time-window views
- improvement tracking
- teacher dashboards
- assignment recommendations
- comparison of before/after remediation diagnoses
- explicit prerequisite-chain mapping

The first version should focus on trustworthy longitudinal interpretation from multiple diagnosis reports.
