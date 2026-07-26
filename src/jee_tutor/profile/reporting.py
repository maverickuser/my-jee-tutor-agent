from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.profile.hierarchical import (
    BroaderConceptualPattern,
    LongitudinalEvidencePack,
    ValidatedRecurringStrand,
)


class OverallSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_scope: str = Field(min_length=1)
    synthesis: str = Field(min_length=1)
    significance: str = Field(min_length=1)
    immediate_student_focus: str = Field(min_length=1)
    immediate_teacher_focus: str = Field(min_length=1)
    primary_strand_ids: list[str] = Field(default_factory=list, max_length=3)
    primary_pattern_ids: list[str] = Field(default_factory=list, max_length=1)


class RecurringStrandReportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strand_id: str
    chapter_family: str
    chapter_labels: list[str]
    topics: list[str]
    title: str
    missing_mental_model: str
    shared_failure: str
    manifestations: list[str]
    corrective_model: str
    diagnosis_report_count: int
    question_count: int
    evidence_references: list[str]
    priority: str
    priority_reason: str
    student_action: str
    teacher_action: str
    verification_check: str


class BroaderPatternReportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    title: str
    shared_reasoning_gap: str
    component_strand_ids: list[str]
    manifestations: list[str]
    relationship_reasoning: str
    diagnosis_report_count: int
    question_count: int
    chapter_family_count: int
    common_corrective_principle: str
    student_action: str
    teacher_action: str
    evidence_references: list[str]


class EvidenceAppendixEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    test_date: str | None
    test_name: str
    subject: str
    question_number: str
    chapter: str
    topic: str
    diagnostic_claim: str
    supported_finding_ids: list[str] = Field(default_factory=list)


class ProfileReportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    overall_summary: OverallSummary
    recurring_gaps: list[RecurringStrandReportEntry] = Field(default_factory=list)
    broader_related_patterns: list[BroaderPatternReportEntry] = Field(
        default_factory=list
    )
    evidence_appendix: list[EvidenceAppendixEntry] = Field(default_factory=list)


class ProfileAnalysisService:
    def generate(self, evidence_pack: LongitudinalEvidencePack) -> ProfileReportOutput:
        recurring_entries = [
            _recurring_entry(item, evidence_pack)
            for item in sorted(
                evidence_pack.recurring_strands,
                key=lambda value: (
                    -value.diagnosis_report_count,
                    -value.question_count,
                    0 if value.strand.confidence == "high" else 1,
                    value.strand.strand_id,
                ),
            )
        ]
        broader_entries = [
            _broader_entry(pattern, evidence_pack)
            for pattern in evidence_pack.broader_patterns
        ]
        report = ProfileReportOutput(
            subject=evidence_pack.subject,
            overall_summary=_overall_summary(
                evidence_pack,
                recurring_entries,
                broader_entries,
            ),
            recurring_gaps=recurring_entries,
            broader_related_patterns=broader_entries,
            evidence_appendix=_evidence_appendix(evidence_pack),
        )
        validate_profile_report(report, evidence_pack)
        return report

    @staticmethod
    def render_markdown(report: ProfileReportOutput) -> str:
        lines = [f"# {report.subject} Longitudinal Profile", "", "## Overall Summary"]
        summary = report.overall_summary
        lines.extend(
            [
                f"- **Evidence scope:** {summary.evidence_scope}",
                f"- **Longitudinal insight:** {summary.synthesis}",
                f"- **Why it matters:** {summary.significance}",
                f"- **Student focus:** {summary.immediate_student_focus}",
                f"- **Teacher focus:** {summary.immediate_teacher_focus}",
                "",
                "## Recurring Gaps",
            ]
        )
        if not report.recurring_gaps:
            lines.append(
                "- No evidence-backed conceptual strand recurs across two independent "
                "diagnosis reports."
            )
        for entry in report.recurring_gaps:
            lines.extend(
                [
                    "",
                    f"### {entry.strand_id} · {entry.title}",
                    f"- **Chapter family:** {entry.chapter_family}",
                    f"- **Related topics:** {'; '.join(entry.topics)}",
                    f"- **Missing mental model:** {entry.missing_mental_model}",
                    f"- **Recurring failure:** {entry.shared_failure}",
                    "- **How it appears across papers:**",
                    *[f"  - {item}" for item in entry.manifestations],
                    f"- **Corrective model:** {entry.corrective_model}",
                    (
                        f"- **Evidence strength:** {entry.diagnosis_report_count} "
                        f"independent reports, {entry.question_count} questions."
                    ),
                    f"- **Priority:** {entry.priority} — {entry.priority_reason}",
                    f"- **Student action:** {entry.student_action}",
                    f"- **Teacher intervention:** {entry.teacher_action}",
                    f"- **Verification check:** {entry.verification_check}",
                    f"- **Evidence:** {'; '.join(entry.evidence_references)}",
                ]
            )
        lines.extend(["", "## Broader Related Patterns"])
        if not report.broader_related_patterns:
            lines.append(
                "- No validated conceptual pattern spans distinct chapter families."
            )
        for entry in report.broader_related_patterns:
            lines.extend(
                [
                    "",
                    f"### {entry.pattern_id} · {entry.title}",
                    f"- **Shared reasoning gap:** {entry.shared_reasoning_gap}",
                    "- **Manifestations by recurring strand:**",
                    *[f"  - {item}" for item in entry.manifestations],
                    f"- **Why they are related:** {entry.relationship_reasoning}",
                    (
                        f"- **Scope:** {entry.chapter_family_count} chapter families, "
                        f"{entry.diagnosis_report_count} reports, "
                        f"{entry.question_count} questions."
                    ),
                    (
                        f"- **Common corrective principle:** "
                        f"{entry.common_corrective_principle}"
                    ),
                    f"- **Student action:** {entry.student_action}",
                    f"- **Teacher intervention:** {entry.teacher_action}",
                    f"- **Evidence:** {'; '.join(entry.evidence_references)}",
                ]
            )
        lines.extend(
            [
                "",
                "## Evidence Appendix",
                "",
                "| Test date | Test | Question | Chapter / topic | "
                "Diagnostic claim | Supports |",
                "|---|---|---:|---|---|---|",
            ]
        )
        for entry in report.evidence_appendix:
            date_label = entry.test_date or "Unavailable"
            supports = ", ".join(entry.supported_finding_ids) or "Not recurring"
            lines.append(
                "| "
                + " | ".join(
                    [
                        _table(date_label),
                        _table(entry.test_name),
                        _table(f"Q{entry.question_number.removeprefix('Q')}"),
                        _table(f"{entry.chapter} / {entry.topic}"),
                        _table(entry.diagnostic_claim),
                        _table(supports),
                    ]
                )
                + " |"
            )
        return "\n".join(lines)


def build_profile_analysis_service_from_environment() -> ProfileAnalysisService:
    return ProfileAnalysisService()


def validate_profile_report(
    report: ProfileReportOutput,
    evidence_pack: LongitudinalEvidencePack,
) -> None:
    if report.subject != evidence_pack.subject:
        raise ValueError("Profile report subject does not match evidence pack.")
    strand_index = {
        item.strand.strand_id: item for item in evidence_pack.recurring_strands
    }
    pattern_index = {
        item.pattern_id: item for item in evidence_pack.broader_patterns
    }
    if {entry.strand_id for entry in report.recurring_gaps} != set(strand_index):
        raise ValueError(
            "Profile report recurring gaps do not match validated conceptual strands."
        )
    if {entry.pattern_id for entry in report.broader_related_patterns} != set(
        pattern_index
    ):
        raise ValueError(
            "Profile report broader patterns do not match validated patterns."
        )
    if not set(report.overall_summary.primary_strand_ids).issubset(strand_index):
        raise ValueError("Overall summary references an unknown recurring strand.")
    if not set(report.overall_summary.primary_pattern_ids).issubset(pattern_index):
        raise ValueError("Overall summary references an unknown broader pattern.")
    expected_evidence = set(evidence_pack.evidence_index)
    appendix_ids = {entry.evidence_id for entry in report.evidence_appendix}
    if appendix_ids != expected_evidence:
        raise ValueError("Evidence appendix does not exactly cover the evidence pack.")
    supported_ids = set(strand_index) | set(pattern_index)
    for entry in report.evidence_appendix:
        if not set(entry.supported_finding_ids).issubset(supported_ids):
            raise ValueError("Evidence appendix references an unknown finding.")
    for entry in report.recurring_gaps:
        source = strand_index[entry.strand_id]
        if entry.diagnosis_report_count != source.diagnosis_report_count:
            raise ValueError("Recurring strand report count does not match evidence.")
        if entry.question_count != source.question_count:
            raise ValueError("Recurring strand question count does not match evidence.")
    for entry in report.broader_related_patterns:
        source = pattern_index[entry.pattern_id]
        if set(entry.component_strand_ids) != set(source.component_strand_ids):
            raise ValueError("Broader pattern components do not match evidence.")


def _overall_summary(
    pack: LongitudinalEvidencePack,
    recurring: list[RecurringStrandReportEntry],
    broader: list[BroaderPatternReportEntry],
) -> OverallSummary:
    primary_strands = recurring[:3]
    primary_patterns = broader[:1]
    if primary_strands:
        synthesis = "The strongest recurring conceptual strands are " + "; ".join(
            f"{item.title} ({item.diagnosis_report_count} papers)"
            for item in primary_strands
        )
        significance = (
            "These are not repeated copies of one question error: each strand links "
            "different manifestations that require the same corrective mental model."
        )
        student_focus = primary_strands[0].student_action
        teacher_focus = primary_strands[0].teacher_action
    else:
        synthesis = (
            "No conceptual strand currently has supported manifestations across two "
            "independent diagnosis reports."
        )
        significance = (
            "The available mistakes remain isolated, non-conceptual, or insufficiently "
            "related; inventing a longitudinal gap would not be evidence-backed."
        )
        student_focus = (
            "Address the diagnosed questions individually while more independent "
            "assessment evidence is collected."
        )
        teacher_focus = (
            "Probe likely concepts directly, but do not treat an isolated mistake as a "
            "persistent student model."
        )
    if primary_patterns:
        synthesis += f". A broader transferable pattern is {primary_patterns[0].title}"
    return OverallSummary(
        evidence_scope=(
            f"Analyzed {pack.question_count} diagnosed questions from "
            f"{pack.diagnosis_report_count} independent diagnosis reports for "
            f"{pack.subject}."
        ),
        synthesis=synthesis + ".",
        significance=significance,
        immediate_student_focus=student_focus,
        immediate_teacher_focus=teacher_focus,
        primary_strand_ids=[item.strand_id for item in primary_strands],
        primary_pattern_ids=[item.pattern_id for item in primary_patterns],
    )


def _recurring_entry(
    item: ValidatedRecurringStrand,
    pack: LongitudinalEvidencePack,
) -> RecurringStrandReportEntry:
    strand = item.strand
    evidence = [pack.evidence_index[eid] for eid in strand.evidence_ids]
    evidence_by_id = {entry.evidence_id: entry for entry in evidence}
    priority = "High" if item.diagnosis_report_count >= 3 else "Medium"
    return RecurringStrandReportEntry(
        strand_id=strand.strand_id,
        chapter_family=strand.chapter_family,
        chapter_labels=strand.chapter_labels,
        topics=strand.topics,
        title=strand.title,
        missing_mental_model=strand.missing_mental_model,
        shared_failure=strand.shared_failure,
        manifestations=[
            (
                f"{evidence_by_id[item.evidence_id].test_name} "
                f"Q{evidence_by_id[item.evidence_id].question_number.removeprefix('Q')}: "
                f"{item.manifestation}"
            )
            for item in strand.manifestations
        ],
        corrective_model=strand.corrective_model,
        diagnosis_report_count=item.diagnosis_report_count,
        question_count=item.question_count,
        evidence_references=[entry.evidence_reference for entry in evidence],
        priority=priority,
        priority_reason=(
            f"One corrective mental model addresses distinct manifestations across "
            f"{item.diagnosis_report_count} independent papers."
        ),
        student_action=(
            f"Before solving mixed {strand.chapter_family} problems, explicitly construct "
            f"and apply this model: {strand.corrective_model}"
        ),
        teacher_action=(
            f"Reteach the model '{strand.missing_mental_model}' using two contrasting "
            "manifestations from the cited papers, then require the student to explain "
            "why the same model governs both."
        ),
        verification_check=(
            f"Give one unfamiliar problem from each of these topics—"
            f"{', '.join(strand.topics)}—and verify that the student states the shared "
            "model before selecting equations."
        ),
    )


def _broader_entry(
    pattern: BroaderConceptualPattern,
    pack: LongitudinalEvidencePack,
) -> BroaderPatternReportEntry:
    strand_index = {
        item.strand.strand_id: item for item in pack.recurring_strands
    }
    components = [
        strand_index[strand_id] for strand_id in pattern.component_strand_ids
    ]
    evidence_ids = _unique(
        eid for component in components for eid in component.strand.evidence_ids
    )
    evidence = [pack.evidence_index[eid] for eid in evidence_ids]
    reports = {entry.diagnosis_report_id for entry in evidence}
    return BroaderPatternReportEntry(
        pattern_id=pattern.pattern_id,
        title=pattern.title,
        shared_reasoning_gap=pattern.shared_reasoning_gap,
        component_strand_ids=pattern.component_strand_ids,
        manifestations=[
            f"{item.chapter_family}: {item.manifestation}"
            for item in pattern.manifestations
        ],
        relationship_reasoning=pattern.rationale,
        diagnosis_report_count=len(reports),
        question_count=len(evidence),
        chapter_family_count=len(
            {component.strand.chapter_family.casefold() for component in components}
        ),
        common_corrective_principle=pattern.common_corrective_principle,
        student_action=(
            "Across mixed-chapter practice, pause before calculation and apply: "
            f"{pattern.common_corrective_principle}"
        ),
        teacher_action=(
            "Use one transfer problem from each component strand and ask the student to "
            "name the shared reasoning operation before solving."
        ),
        evidence_references=[entry.evidence_reference for entry in evidence],
    )


def _evidence_appendix(
    pack: LongitudinalEvidencePack,
) -> list[EvidenceAppendixEntry]:
    strand_support: dict[str, list[str]] = {}
    for recurring in pack.recurring_strands:
        for evidence_id in recurring.strand.evidence_ids:
            strand_support.setdefault(evidence_id, []).append(
                recurring.strand.strand_id
            )
    strand_index = {
        item.strand.strand_id: item for item in pack.recurring_strands
    }
    pattern_support: dict[str, list[str]] = {}
    for pattern in pack.broader_patterns:
        for strand_id in pattern.component_strand_ids:
            for evidence_id in strand_index[strand_id].strand.evidence_ids:
                pattern_support.setdefault(evidence_id, []).append(pattern.pattern_id)
    return [
        EvidenceAppendixEntry(
            evidence_id=item.evidence_id,
            test_date=item.test_date,
            test_name=item.test_name,
            subject=item.subject,
            question_number=item.question_number,
            chapter=item.canonical_chapter,
            topic=item.canonical_topic,
            diagnostic_claim=item.exact_concept_gap,
            supported_finding_ids=_unique(
                [
                    *strand_support.get(item.evidence_id, []),
                    *pattern_support.get(item.evidence_id, []),
                ]
            ),
        )
        for item in sorted(
            pack.evidence_index.values(),
            key=lambda value: (
                value.test_date or "9999-12-31",
                value.test_name.casefold(),
                _question_sort_key(value.question_number),
            ),
        )
    ]


def _table(value: str) -> str:
    return " ".join(value.replace("|", "\\|").split())


def _question_sort_key(value: str) -> tuple[int, str]:
    normalized = value.strip().removeprefix("Q").removeprefix("q")
    return (int(normalized), "") if normalized.isdigit() else (10**9, normalized)


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
