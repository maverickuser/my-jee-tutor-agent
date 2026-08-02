"""Evidence-backed, student-facing profile insight generation."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.profile.evidence import ProfileEvidenceItem
from jee_tutor.profile.hierarchical import ConceptualStrandOutput, recurring_conceptual_strands


FailureType = Literal[
    "concept_not_applied",
    "concept_applied_incorrectly",
    "concept_applied_incompletely",
    "execution",
    "attention",
    "strategy_representation",
]
Confidence = Literal["high", "medium", "low"]
ReasoningProvenance = Literal["observed_working", "inferred_from_diagnosis"]
MAX_PROFILE_INSIGHTS = 3
MAX_IMPORTANT_CHAPTERS = 5

_FAILURE_KEYWORDS: tuple[tuple[FailureType, tuple[str, ...]], ...] = (
    ("execution", ("calculation", "arithmetic", "algebra", "sign error")),
    ("attention", ("misread", "overlook", "careless", "unit")),
    ("strategy_representation", ("diagram", "represent", "wrong approach", "strategy")),
    (
        "concept_applied_incompletely",
        ("only one", "all cases", "every case", "incomplete", "missed"),
    ),
    ("concept_applied_incorrectly", ("incorrect", "wrongly", "misapplied", "confused")),
)

_HEADINGS: dict[FailureType, str] = {
    "concept_not_applied": "What rule should I use before I start?",
    "concept_applied_incorrectly": "Am I using this rule in the right way?",
    "concept_applied_incompletely": "Have I checked every possible case?",
    "execution": "Did I check each calculation and sign?",
    "attention": "What detail in the question can change my answer?",
    "strategy_representation": "Would a diagram or a simpler form make this clear?",
}

_PREVENTIVE_ACTIONS: dict[FailureType, str] = {
    "concept_not_applied": "Write the relevant rule before substituting values.",
    "concept_applied_incorrectly": "State what the rule means and check its conditions.",
    "concept_applied_incompletely": (
        "List the cases first, solve each one, then combine the answers."
    ),
    "execution": "Work one line at a time and do a sign, unit, and substitution check.",
    "attention": "Underline the condition, unit, and exact quantity being asked.",
    "strategy_representation": "Draw or rewrite the information before choosing an equation.",
}

_SUBJECT_CUES = {
    "maths": "different cases, ranges, roots, graphs, or modulus",
    "mathematics": "different cases, ranges, roots, graphs, or modulus",
    "physics": "a diagram, direction, component, unit, or limiting case",
    "chemistry": "a reaction condition, exception, trend, or species comparison",
}


class QuestionFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_reference: str
    diagnosis_json_s3_uri: str
    chapter: str
    topic: str
    concept_gap: str
    first_divergence: str
    failure_type: FailureType
    reasoning_provenance: ReasoningProvenance
    confidence: Confidence


class InsightEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insight_id: str
    confidence: Confidence
    supporting_questions: list[QuestionFailure] = Field(min_length=2)
    shared_failure: str
    preventive_action: str
    likely_mark_impact: int = Field(ge=1)


class StudentActionableInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1)
    do: str = Field(min_length=1)
    ask_this_when_you_see: str = Field(min_length=1)


class ImportantChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter: str
    mistake_count: int = Field(ge=2)
    combined_weightage_percent: float = Field(gt=0)


class ActionableProfileReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    title: str
    insights: list[StudentActionableInsight] = Field(
        default_factory=list, max_length=MAX_PROFILE_INSIGHTS
    )
    important_chapters_to_fix_first: list[ImportantChapter] = Field(
        default_factory=list, max_length=MAX_IMPORTANT_CHAPTERS
    )
    internal_evidence: list[InsightEvidence] = Field(default_factory=list)
    question_level_feedback: list[QuestionFailure] = Field(default_factory=list)


class ActionableInsightService:
    """Turns validated recurring strands into prospective student actions.

    Embeddings only create candidates in ConceptualStrandAnalyzer. This service accepts
    only strands that survived structured-evidence validation and recur in two reports.
    """

    def __init__(self, *, failure_classifier: "QuestionFailureClassifier | None" = None):
        self.failure_classifier = failure_classifier or QuestionFailureClassifier()

    def generate(
        self,
        *,
        subject: str,
        evidence_items: list[ProfileEvidenceItem],
        strand_output: ConceptualStrandOutput,
        important_chapters: list[ImportantChapter] | None = None,
    ) -> ActionableProfileReport:
        evidence_index = {item.evidence_id: item for item in evidence_items}
        failures = {
            item.evidence_id: self.failure_classifier.classify(item)
            for item in evidence_items
        }
        recurring = recurring_conceptual_strands(strand_output.strands, evidence_index)
        ranked = sorted(
            recurring,
            key=lambda item: (
                -item.diagnosis_report_count,
                -item.question_count,
                0 if item.strand.confidence == "high" else 1,
                item.strand.strand_id,
            ),
        )

        insights: list[StudentActionableInsight] = []
        metadata: list[InsightEvidence] = []
        used: set[str] = set()
        for recurring_strand in ranked:
            strand = recurring_strand.strand
            supporting = [failures[evidence_id] for evidence_id in strand.evidence_ids]
            failure_type = Counter(item.failure_type for item in supporting).most_common(1)[0][0]
            action = _preventive_action(failure_type)
            insights.append(
                StudentActionableInsight(
                    heading=_heading(failure_type),
                    do=action,
                    ask_this_when_you_see=_trigger(subject, strand.topics),
                )
            )
            metadata.append(
                InsightEvidence(
                    insight_id=strand.strand_id,
                    confidence=strand.confidence,
                    supporting_questions=supporting,
                    shared_failure=strand.shared_failure,
                    preventive_action=action,
                    likely_mark_impact=recurring_strand.question_count,
                )
            )
            used.update(strand.evidence_ids)
            if len(insights) == MAX_PROFILE_INSIGHTS:
                break

        return ActionableProfileReport(
            subject=subject,
            title=f"{subject} — What to do differently next time",
            insights=insights,
            important_chapters_to_fix_first=important_chapters or [],
            internal_evidence=metadata,
            question_level_feedback=[
                failures[item.evidence_id]
                for item in evidence_items
                if item.evidence_id not in used
            ],
        )

    @staticmethod
    def render_markdown(report: ActionableProfileReport) -> str:
        lines = [f"# {report.title}", ""]
        if report.important_chapters_to_fix_first:
            lines.extend(["## Chapters to fix first", ""])
            for item in report.important_chapters_to_fix_first:
                lines.append(
                    f"- {item.chapter} — {item.mistake_count} mistakes; "
                    f"about {item.combined_weightage_percent:g}% JEE weightage"
                )
            lines.append("")
        if not report.insights:
            lines.extend(
                [
                    "No mistake pattern has repeated enough yet.",
                    "",
                    "For now, correct each diagnosed question separately.",
                ]
            )
        for insight in report.insights:
            lines.extend(
                [
                    f"## {insight.heading}",
                    "",
                    f"**Do:** {insight.do}",
                    "",
                    f"**Ask this when you see:** {insight.ask_this_when_you_see}",
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"


class QuestionFailureClassifier:
    """Classify the first described divergence using deterministic evidence rules."""

    def classify(self, item: ProfileEvidenceItem) -> QuestionFailure:
        text = " ".join(
            (item.exact_concept_gap, item.likely_thought, item.why_wrong)
        ).casefold()
        failure_type = self._failure_type(text)
        return QuestionFailure(
            evidence_id=item.evidence_id,
            evidence_reference=item.evidence_reference,
            diagnosis_json_s3_uri=item.diagnosis_json_s3_uri,
            chapter=item.chapter,
            topic=item.topic,
            concept_gap=item.exact_concept_gap,
            first_divergence=item.why_wrong,
            failure_type=failure_type,
            reasoning_provenance="inferred_from_diagnosis",
            confidence="medium",
        )

    @staticmethod
    def _failure_type(text: str) -> FailureType:
        for failure_type, keywords in _FAILURE_KEYWORDS:
            if any(keyword in text for keyword in keywords):
                return failure_type
        return "concept_not_applied"


def _heading(failure_type: FailureType) -> str:
    return _HEADINGS[failure_type]


def _preventive_action(failure_type: FailureType) -> str:
    return _PREVENTIVE_ACTIONS[failure_type]


def _trigger(subject: str, topics: list[str]) -> str:
    topic_text = ", ".join(topics[:3])
    subject_cue = _SUBJECT_CUES.get(
        subject.casefold(),
        "a question with conditions or more than one possible case",
    )
    return f"a {topic_text} question involving {subject_cue}."


__all__ = [
    "ActionableInsightService",
    "ActionableProfileReport",
    "ImportantChapter",
    "InsightEvidence",
    "QuestionFailure",
    "QuestionFailureClassifier",
    "StudentActionableInsight",
]
