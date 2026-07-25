from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.profile.hierarchical import (
    BroaderConceptualPattern,
    LongitudinalEvidencePack,
    ValidatedRecurringGap,
)


class OverallSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_scope: str = Field(min_length=1)
    synthesis: str = Field(min_length=1)
    immediate_student_focus: str = Field(min_length=1)
    immediate_teacher_focus: str = Field(min_length=1)
    primary_gap_ids: list[str] = Field(default_factory=list, max_length=2)
    primary_pattern_ids: list[str] = Field(default_factory=list, max_length=1)


class RecurringGapReportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str
    chapter: str
    topic: str
    title: str
    concept_gap: str
    shared_misconception: str
    same_gap_reasoning: str
    diagnosis_report_count: int
    question_count: int
    evidence_references: list[str]
    priority: str
    priority_reason: str
    student_action: str
    teacher_action: str


class BroaderPatternReportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    title: str
    shared_reasoning_gap: str
    component_gap_ids: list[str]
    manifestations: list[str]
    relationship_reasoning: str
    diagnosis_report_count: int
    question_count: int
    chapter_count: int
    topic_count: int
    instructional_value: str
    student_action: str
    teacher_action: str
    evidence_references: list[str]


class EvidenceAppendixEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    test_date: str | None
    diagnosis_date: str
    test_name: str
    subject: str
    question_number: str
    chapter: str
    topic: str
    exact_concept_gap: str
    likely_thought: str
    why_wrong: str
    corrective_recommendation: str
    source_report_id: str


class ProfileReportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    overall_summary: OverallSummary
    recurring_gaps: list[RecurringGapReportEntry] = Field(default_factory=list)
    broader_related_patterns: list[BroaderPatternReportEntry] = Field(
        default_factory=list
    )
    evidence_appendix: list[EvidenceAppendixEntry] = Field(default_factory=list)


class ProfileAnalysisService:
    def generate(self, evidence_pack: LongitudinalEvidencePack) -> ProfileReportOutput:
        recurring_entries = [
            _recurring_entry(item, evidence_pack)
            for item in sorted(
                evidence_pack.recurring_gaps,
                key=lambda value: (
                    -value.diagnosis_report_count,
                    -value.question_count,
                    value.gap.gap_id,
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
                f"- **Key insight:** {summary.synthesis}",
                f"- **Student focus:** {summary.immediate_student_focus}",
                f"- **Teacher focus:** {summary.immediate_teacher_focus}",
                "",
                "## Recurring Gaps",
            ]
        )
        if not report.recurring_gaps:
            lines.append("- No concept gap is recurring across two diagnosis reports yet.")
        for entry in report.recurring_gaps:
            lines.extend(
                [
                    "",
                    f"### {entry.chapter} → {entry.topic}: {entry.title}",
                    f"- **Concept gap:** {entry.concept_gap}",
                    f"- **Recurring misconception:** {entry.shared_misconception}",
                    f"- **Why this is the same gap:** {entry.same_gap_reasoning}",
                    (
                        f"- **Evidence strength:** {entry.diagnosis_report_count} diagnosis "
                        f"reports, {entry.question_count} questions."
                    ),
                    f"- **Priority:** {entry.priority} — {entry.priority_reason}",
                    f"- **Student action:** {entry.student_action}",
                    f"- **Teacher action:** {entry.teacher_action}",
                    f"- **Evidence:** {'; '.join(entry.evidence_references)}",
                ]
            )
        lines.extend(["", "## Broader Related Patterns"])
        if not report.broader_related_patterns:
            lines.append(
                "- No validated conceptual pattern spans distinct chapter/topic contexts yet."
            )
        for entry in report.broader_related_patterns:
            lines.extend(
                [
                    "",
                    f"### {entry.title}",
                    f"- **Shared reasoning gap:** {entry.shared_reasoning_gap}",
                    f"- **Manifestations:** {'; '.join(entry.manifestations)}",
                    f"- **Why these gaps are related:** {entry.relationship_reasoning}",
                    (
                        f"- **Scope:** {entry.chapter_count} chapters, {entry.topic_count} "
                        f"topics, {entry.diagnosis_report_count} reports, "
                        f"{entry.question_count} questions."
                    ),
                    f"- **Instructional value:** {entry.instructional_value}",
                    f"- **Student action:** {entry.student_action}",
                    f"- **Teacher action:** {entry.teacher_action}",
                    f"- **Evidence:** {'; '.join(entry.evidence_references)}",
                ]
            )
        lines.extend(["", "## Evidence Appendix"])
        for entry in report.evidence_appendix:
            date_label = entry.test_date or "Test date unavailable"
            lines.extend(
                [
                    "",
                    (
                        f"### {date_label} · {entry.test_name} · "
                        f"{entry.subject} · Q{entry.question_number.removeprefix('Q')}"
                    ),
                    f"- **Chapter:** {entry.chapter}",
                    f"- **Topic:** {entry.topic}",
                    f"- **Concept gap:** {entry.exact_concept_gap}",
                    f"- **Likely reasoning:** {entry.likely_thought}",
                    f"- **Why it was wrong:** {entry.why_wrong}",
                    f"- **Required correction:** {entry.corrective_recommendation}",
                    f"- **Source diagnosis:** {entry.source_report_id}",
                    f"- **Diagnosis date:** {entry.diagnosis_date}",
                ]
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
    gap_index = {item.gap.gap_id: item for item in evidence_pack.recurring_gaps}
    pattern_index = {
        item.pattern_id: item for item in evidence_pack.broader_patterns
    }
    if set(entry.gap_id for entry in report.recurring_gaps) != set(gap_index):
        raise ValueError("Profile report recurring gaps do not match validated local gaps.")
    if set(entry.pattern_id for entry in report.broader_related_patterns) != set(
        pattern_index
    ):
        raise ValueError("Profile report broader patterns do not match validated patterns.")
    if not set(report.overall_summary.primary_gap_ids).issubset(gap_index):
        raise ValueError("Overall summary references an unknown recurring gap.")
    if not set(report.overall_summary.primary_pattern_ids).issubset(pattern_index):
        raise ValueError("Overall summary references an unknown broader pattern.")
    expected_evidence = set(evidence_pack.evidence_index)
    appendix_ids = {entry.evidence_id for entry in report.evidence_appendix}
    if appendix_ids != expected_evidence:
        raise ValueError("Evidence appendix does not exactly cover the evidence pack.")
    for entry in report.recurring_gaps:
        source = gap_index[entry.gap_id]
        if entry.diagnosis_report_count != source.diagnosis_report_count:
            raise ValueError("Recurring gap report count does not match evidence.")
        if entry.question_count != source.question_count:
            raise ValueError("Recurring gap question count does not match evidence.")
    for entry in report.broader_related_patterns:
        source = pattern_index[entry.pattern_id]
        if set(entry.component_gap_ids) != set(source.component_gap_ids):
            raise ValueError("Broader pattern components do not match evidence.")


def _overall_summary(
    pack: LongitudinalEvidencePack,
    recurring: list[RecurringGapReportEntry],
    broader: list[BroaderPatternReportEntry],
) -> OverallSummary:
    primary_gaps = recurring[:2]
    primary_patterns = broader[:1]
    gap_text = (
        "; ".join(
            f"{item.chapter}/{item.topic}: {item.title}" for item in primary_gaps
        )
        or "No exact concept gap is recurring across two reports yet"
    )
    pattern_text = (
        f" Broader pattern: {primary_patterns[0].title}."
        if primary_patterns
        else ""
    )
    return OverallSummary(
        evidence_scope=(
            f"Analyzed {pack.question_count} diagnosed questions from "
            f"{pack.diagnosis_report_count} diagnosis reports for {pack.subject}."
        ),
        synthesis=f"Highest-priority recurring findings: {gap_text}.{pattern_text}",
        immediate_student_focus=(
            primary_gaps[0].student_action
            if primary_gaps
            else "Continue collecting diagnosis evidence across assessments."
        ),
        immediate_teacher_focus=(
            primary_gaps[0].teacher_action
            if primary_gaps
            else "Monitor future assessments for repeatable concept gaps."
        ),
        primary_gap_ids=[item.gap_id for item in primary_gaps],
        primary_pattern_ids=[item.pattern_id for item in primary_patterns],
    )


def _recurring_entry(
    item: ValidatedRecurringGap,
    pack: LongitudinalEvidencePack,
) -> RecurringGapReportEntry:
    gap = item.gap
    evidence = [pack.evidence_index[eid] for eid in gap.evidence_ids]
    priority = "High" if item.diagnosis_report_count >= 3 else "Medium"
    return RecurringGapReportEntry(
        gap_id=gap.gap_id,
        chapter=gap.canonical_chapter,
        topic=gap.canonical_topic,
        title=gap.concept_gap,
        concept_gap=gap.concept_gap,
        shared_misconception=gap.shared_misconception,
        same_gap_reasoning=gap.rationale,
        diagnosis_report_count=item.diagnosis_report_count,
        question_count=item.question_count,
        evidence_references=[entry.evidence_reference for entry in evidence],
        priority=priority,
        priority_reason=(
            f"The same conceptual correction is needed across "
            f"{item.diagnosis_report_count} independent diagnosis reports."
        ),
        student_action=(
            f"Practise {gap.canonical_topic} problems by first stating and applying: "
            f"{gap.corrective_concept}"
        ),
        teacher_action=(
            f"Verify and reteach {gap.required_concept}; directly challenge the belief that "
            f"{gap.shared_misconception}"
        ),
    )


def _broader_entry(
    pattern: BroaderConceptualPattern,
    pack: LongitudinalEvidencePack,
) -> BroaderPatternReportEntry:
    gap_index = {item.gap.gap_id: item for item in pack.recurring_gaps}
    components = [gap_index[gap_id] for gap_id in pattern.component_gap_ids]
    evidence_ids = _unique(
        eid for component in components for eid in component.gap.evidence_ids
    )
    evidence = [pack.evidence_index[eid] for eid in evidence_ids]
    chapters = {component.gap.canonical_chapter.casefold() for component in components}
    topics = {component.gap.canonical_topic.casefold() for component in components}
    reports = {entry.diagnosis_report_id for entry in evidence}
    return BroaderPatternReportEntry(
        pattern_id=pattern.pattern_id,
        title=pattern.title,
        shared_reasoning_gap=pattern.shared_reasoning_gap,
        component_gap_ids=pattern.component_gap_ids,
        manifestations=[
            (
                f"{item.chapter} → {item.topic}: {item.manifestation}"
            )
            for item in pattern.manifestations
        ],
        relationship_reasoning=pattern.rationale,
        diagnosis_report_count=len(reports),
        question_count=len(evidence),
        chapter_count=len(chapters),
        topic_count=len(topics),
        instructional_value=(
            "One transferable reasoning routine can reinforce the connected local concepts: "
            f"{pattern.common_corrective_principle}"
        ),
        student_action=(
            "Across mixed-topic practice, explicitly apply this reasoning rule before "
            f"calculation: {pattern.common_corrective_principle}"
        ),
        teacher_action=(
            "Use one problem from each manifestation to verify transfer of the corrective "
            f"principle: {pattern.common_corrective_principle}"
        ),
        evidence_references=[entry.evidence_reference for entry in evidence],
    )


def _evidence_appendix(
    pack: LongitudinalEvidencePack,
) -> list[EvidenceAppendixEntry]:
    return [
        EvidenceAppendixEntry(
            evidence_id=item.evidence_id,
            test_date=item.test_date,
            diagnosis_date=item.diagnosis_date,
            test_name=item.test_name,
            subject=item.subject,
            question_number=item.question_number,
            chapter=item.canonical_chapter,
            topic=item.canonical_topic,
            exact_concept_gap=item.exact_concept_gap,
            likely_thought=item.likely_thought,
            why_wrong=item.why_wrong,
            corrective_recommendation=item.deep_dive_recommendation,
            source_report_id=item.diagnosis_report_id,
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


def _question_sort_key(value: str) -> tuple[int, str]:
    normalized = value.strip().removeprefix("Q").removeprefix("q")
    return (int(normalized), "") if normalized.isdigit() else (10**9, normalized)


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
