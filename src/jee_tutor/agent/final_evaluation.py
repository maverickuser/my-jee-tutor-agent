from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.diagnosis_output import DiagnosisResponse, UNREADABLE_SENTINEL


EVALUATOR_SCHEMA_NAME = "jee_final_evaluator_assessment"
EVALUATOR_SCHEMA_VERSION = 1
DIAGNOSIS_FIELD_NAMES = (
    "question_number",
    "chapter",
    "topic",
    "what_you_thought",
    "why_that_thought_is_wrong",
    "exact_concept_gap",
    "what_you_must_deep_dive",
)
DiagnosisFieldName = Literal[
    "question_number",
    "chapter",
    "topic",
    "what_you_thought",
    "why_that_thought_is_wrong",
    "exact_concept_gap",
    "what_you_must_deep_dive",
]
CompletenessItemName = Literal[
    "question_number",
    "chapter",
    "topic",
    "what_you_thought",
    "why_that_thought_is_wrong",
    "exact_concept_gap",
    "what_you_must_deep_dive",
    "missed_option_concepts",
    "unattempted_reason",
]
InferenceCriterionName = Literal[
    "evidence_alignment",
    "qualification",
    "specificity",
    "no_overclaiming",
    "root_cause_linkage",
]


class InferenceRating(StrEnum):
    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"

    @property
    def score(self) -> float:
        return {
            self.MET: 1.0,
            self.PARTIAL: 0.5,
            self.NOT_MET: 0.0,
        }[self]


class ClaimKind(StrEnum):
    OBSERVATION = "observation"
    INFERENCE = "inference"
    RECOMMENDATION = "recommendation"


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class FinalDecision(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class ClaimEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    field_name: DiagnosisFieldName
    claim_kind: ClaimKind
    status: ClaimStatus
    evidence_summary: str = Field(min_length=1, max_length=500)
    issue_summary: str | None = Field(default=None, min_length=1, max_length=500)
    critical: bool = False

    @field_validator("evidence_summary", "issue_summary", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CriterionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=0.0, le=1.0)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class EvaluatorClaim(BaseModel):
    """Flat model-facing claim record used to keep Gemini's schema shallow."""

    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    field_name: DiagnosisFieldName
    claim_kind: ClaimKind
    status: ClaimStatus
    evidence_summary: str = Field(min_length=1, max_length=500)
    issue_summary: str = Field(max_length=500)
    critical: bool

    @field_validator("evidence_summary", "issue_summary", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class EvaluatorCompletenessItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    item_name: CompletenessItemName
    satisfied: bool


class EvaluatorInferenceRating(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    criterion_name: InferenceCriterionName
    rating: InferenceRating


class EvaluatorTransportAssessment(BaseModel):
    """Gemini-compatible transport shape converted into EvaluatorAssessment."""

    model_config = ConfigDict(extra="forbid")

    claims: list[EvaluatorClaim] = Field(min_length=1, max_length=1000)
    completeness_items: list[EvaluatorCompletenessItem] = Field(
        min_length=1,
        max_length=900,
    )
    inference_ratings: list[EvaluatorInferenceRating] = Field(max_length=500)
    evaluator_summary: str = Field(min_length=1, max_length=1000)

    @field_validator("evaluator_summary", mode="before")
    @classmethod
    def strip_summary(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class QuestionEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    question_number: str = Field(min_length=1, max_length=100)
    claims: list[ClaimEvaluation] = Field(max_length=100)
    applicable_completeness_items: list[str] = Field(max_length=9)
    satisfied_completeness_items: list[str] = Field(max_length=9)
    inference_criteria_scores: list[CriterionScore] = Field(max_length=5)
    issues: list[str] = Field(default_factory=list, max_length=10)

    @field_validator(
        "question_number",
        "applicable_completeness_items",
        "satisfied_completeness_items",
        "issues",
        mode="before",
    )
    @classmethod
    def strip_bounded_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value

    @model_validator(mode="after")
    def validate_references(self) -> "QuestionEvaluation":
        if any(claim.row_index != self.row_index for claim in self.claims):
            raise ValueError("Every claim row_index must match its question row_index.")
        applicable = self.applicable_completeness_items
        satisfied = self.satisfied_completeness_items
        if len(set(applicable)) != len(applicable) or len(set(satisfied)) != len(satisfied):
            raise ValueError("Completeness item references must be unique.")
        if not set(satisfied).issubset(applicable):
            raise ValueError("Satisfied completeness items must be applicable.")
        names = [item.name for item in self.inference_criteria_scores]
        if len(set(names)) != len(names):
            raise ValueError("Inference criteria score names must be unique.")
        return self


class EvaluatorAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = EVALUATOR_SCHEMA_VERSION
    questions: list[QuestionEvaluation] = Field(min_length=1, max_length=100)
    evaluator_summary: str = Field(min_length=1, max_length=1000)

    @field_validator("evaluator_summary", mode="before")
    @classmethod
    def strip_summary(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


def evaluator_response_format() -> dict[str, object]:
    """Return a shallow schema that stays within Gemini's complexity budget."""

    schema = EvaluatorTransportAssessment.model_json_schema()
    _remove_provider_schema_metadata(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": EVALUATOR_SCHEMA_NAME,
            "strict": True,
            "schema": schema,
        },
    }


def build_evaluator_assessment(
    transport: EvaluatorTransportAssessment,
    diagnosis: DiagnosisResponse,
) -> EvaluatorAssessment:
    question_count = len(diagnosis.questions)
    row_indexes = [
        *(claim.row_index for claim in transport.claims),
        *(item.row_index for item in transport.completeness_items),
        *(rating.row_index for rating in transport.inference_ratings),
    ]
    if any(row_index >= question_count for row_index in row_indexes):
        raise EvaluationCalculationError("Evaluator referenced an unknown diagnosis row.")

    questions: list[QuestionEvaluation] = []
    for row_index, diagnosis_question in enumerate(diagnosis.questions):
        claims = [claim for claim in transport.claims if claim.row_index == row_index]
        completeness = [
            item for item in transport.completeness_items if item.row_index == row_index
        ]
        inference_ratings = [
            rating for rating in transport.inference_ratings if rating.row_index == row_index
        ]
        questions.append(
            QuestionEvaluation(
                row_index=row_index,
                question_number=diagnosis_question.question_number,
                claims=[
                    ClaimEvaluation(
                        row_index=claim.row_index,
                        field_name=claim.field_name,
                        claim_kind=claim.claim_kind,
                        status=claim.status,
                        evidence_summary=claim.evidence_summary,
                        issue_summary=claim.issue_summary or None,
                        critical=claim.critical,
                    )
                    for claim in claims
                ],
                applicable_completeness_items=[item.item_name for item in completeness],
                satisfied_completeness_items=[
                    item.item_name for item in completeness if item.satisfied
                ],
                inference_criteria_scores=[
                    CriterionScore(
                        name=rating.criterion_name,
                        score=rating.rating.score,
                    )
                    for rating in inference_ratings
                ],
                issues=list(
                    dict.fromkeys(claim.issue_summary for claim in claims if claim.issue_summary)
                ),
            )
        )
    return EvaluatorAssessment(
        schema_version=EVALUATOR_SCHEMA_VERSION,
        questions=questions,
        evaluator_summary=transport.evaluator_summary,
    )


def _remove_provider_schema_metadata(value: object) -> None:
    """Drop locally validated constraints that consume Gemini schema complexity."""

    if isinstance(value, dict):
        for key in (
            "additionalProperties",
            "default",
            "maxItems",
            "maxLength",
            "maximum",
            "minItems",
            "minLength",
            "minimum",
            "title",
        ):
            value.pop(key, None)
        for child in value.values():
            _remove_provider_schema_metadata(child)
    elif isinstance(value, list):
        for child in value:
            _remove_provider_schema_metadata(child)


class EvaluationCalculationError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationMetrics:
    groundedness_score: float
    unsupported_claim_rate: float
    contradiction_rate: float
    completeness_score: float
    inference_quality_score: float
    supported_claim_count: int
    unsupported_claim_count: int
    contradicted_claim_count: int
    total_claim_count: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "groundedness_score": self.groundedness_score,
            "unsupported_claim_rate": self.unsupported_claim_rate,
            "contradiction_rate": self.contradiction_rate,
            "completeness_score": self.completeness_score,
            "inference_quality_score": self.inference_quality_score,
            "supported_claim_count": self.supported_claim_count,
            "unsupported_claim_count": self.unsupported_claim_count,
            "contradicted_claim_count": self.contradicted_claim_count,
            "total_claim_count": self.total_claim_count,
        }


@dataclass(frozen=True)
class DecisionResult:
    decision: FinalDecision
    failed_thresholds: tuple[str, ...]
    critical_issue_count: int

    @property
    def artifact_allowed(self) -> bool:
        return self.decision == FinalDecision.PASS


@dataclass(frozen=True)
class EvaluationThresholds:
    pass_groundedness_score: float = 0.90
    pass_unsupported_claim_rate: float = 0.05
    pass_contradiction_rate: float = 0.00
    pass_completeness_score: float = 0.90
    pass_inference_quality_score: float = 0.80
    review_groundedness_score: float = 0.75
    review_unsupported_claim_rate: float = 0.20
    review_contradiction_rate: float = 0.05
    review_completeness_score: float = 0.75
    review_inference_quality_score: float = 0.65

    def __post_init__(self) -> None:
        values = vars(self)
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values.values()):
            raise ValueError("Final evaluator thresholds must be finite values from 0 to 1.")
        if (
            self.pass_groundedness_score < self.review_groundedness_score
            or self.pass_unsupported_claim_rate > self.review_unsupported_claim_rate
            or self.pass_contradiction_rate > self.review_contradiction_rate
            or self.pass_completeness_score < self.review_completeness_score
            or self.pass_inference_quality_score < self.review_inference_quality_score
        ):
            raise ValueError("Pass thresholds must be at least as strict as review thresholds.")

    @classmethod
    def from_config(cls, config: LLMConfig | None = None) -> "EvaluationThresholds":
        values = (config or LLMConfig.load()).section("final_evaluator")
        defaults = cls()
        return cls(
            **{
                field_name: float(values.get(field_name, getattr(defaults, field_name)))
                for field_name in vars(defaults)
            }
        )


def validate_assessment_references(
    assessment: EvaluatorAssessment,
    diagnosis: DiagnosisResponse,
) -> None:
    if len(assessment.questions) != len(diagnosis.questions):
        raise EvaluationCalculationError("Evaluator question count does not match diagnosis.")
    for index, (finding, question) in enumerate(zip(assessment.questions, diagnosis.questions)):
        if finding.row_index != index:
            raise EvaluationCalculationError("Evaluator row order does not match diagnosis.")
        if finding.question_number.strip() != question.question_number.strip():
            raise EvaluationCalculationError(
                "Evaluator question reference does not match diagnosis."
            )
        covered_fields = {claim.field_name for claim in finding.claims} | set(
            finding.applicable_completeness_items
        )
        if set(DIAGNOSIS_FIELD_NAMES) - covered_fields:
            raise EvaluationCalculationError(
                "Evaluator findings do not cover every diagnosis field."
            )


def calculate_metrics(
    assessment: EvaluatorAssessment,
    diagnosis: DiagnosisResponse | None = None,
) -> EvaluationMetrics:
    claims = [claim for question in assessment.questions for claim in question.claims]
    supported = sum(claim.status == ClaimStatus.SUPPORTED for claim in claims)
    unsupported = sum(claim.status == ClaimStatus.UNSUPPORTED for claim in claims)
    contradicted = sum(claim.status == ClaimStatus.CONTRADICTED for claim in claims)
    total = supported + unsupported + contradicted
    if total == 0:
        raise EvaluationCalculationError("Evaluator produced no classifiable claims.")

    applicable = sum(
        len(question.applicable_completeness_items) for question in assessment.questions
    )
    satisfied = sum(len(question.satisfied_completeness_items) for question in assessment.questions)
    if applicable == 0:
        raise EvaluationCalculationError("Evaluator produced no applicable completeness items.")

    inference_scores = [
        score.score
        for question in assessment.questions
        for score in question.inference_criteria_scores
    ]
    if inference_scores:
        inference_quality = sum(inference_scores) / len(inference_scores)
    elif diagnosis and all(
        question.question_number.casefold() == UNREADABLE_SENTINEL.casefold()
        for question in diagnosis.questions
    ):
        inference_quality = 1.0
    else:
        raise EvaluationCalculationError("Evaluator omitted applicable inference criteria.")

    raw_values = (
        supported / total,
        unsupported / total,
        contradicted / total,
        satisfied / applicable,
        inference_quality,
    )
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in raw_values):
        raise EvaluationCalculationError("Evaluator metrics are not finite values from 0 to 1.")
    if not math.isclose(sum(raw_values[:3]), 1.0, abs_tol=1e-9):
        raise EvaluationCalculationError("Evaluator claim rates are internally inconsistent.")

    rounded = tuple(round(value, 4) for value in raw_values)
    return EvaluationMetrics(
        groundedness_score=rounded[0],
        unsupported_claim_rate=rounded[1],
        contradiction_rate=rounded[2],
        completeness_score=rounded[3],
        inference_quality_score=rounded[4],
        supported_claim_count=supported,
        unsupported_claim_count=unsupported,
        contradicted_claim_count=contradicted,
        total_claim_count=total,
    )


def decide_evaluation(
    assessment: EvaluatorAssessment,
    metrics: EvaluationMetrics,
    thresholds: EvaluationThresholds | None = None,
) -> DecisionResult:
    policy = thresholds or EvaluationThresholds()
    critical_count = sum(
        claim.critical and claim.status == ClaimStatus.CONTRADICTED
        for question in assessment.questions
        for claim in question.claims
    )
    pass_failures = _failed_thresholds(metrics, policy, "pass")
    review_failures = _failed_thresholds(metrics, policy, "review")
    if critical_count:
        return DecisionResult(
            decision=FinalDecision.REJECT,
            failed_thresholds=("critical_contradiction", *review_failures),
            critical_issue_count=critical_count,
        )
    if not pass_failures:
        return DecisionResult(FinalDecision.PASS, (), 0)
    if not review_failures:
        return DecisionResult(FinalDecision.REVIEW, pass_failures, 0)
    return DecisionResult(FinalDecision.REJECT, review_failures, 0)


def _failed_thresholds(
    metrics: EvaluationMetrics,
    thresholds: EvaluationThresholds,
    prefix: str,
) -> tuple[str, ...]:
    minimums = ("groundedness_score", "completeness_score", "inference_quality_score")
    maximums = ("unsupported_claim_rate", "contradiction_rate")
    failed = [
        name
        for name in minimums
        if getattr(metrics, name) < getattr(thresholds, f"{prefix}_{name}")
    ]
    failed.extend(
        name
        for name in maximums
        if getattr(metrics, name) > getattr(thresholds, f"{prefix}_{name}")
    )
    return tuple(failed)


class FinalEvaluationError(RuntimeError):
    def __init__(
        self,
        message: str = "Analysis did not pass final quality evaluation.",
        *,
        decision: FinalDecision = FinalDecision.REJECT,
        metrics: EvaluationMetrics | None = None,
        failed_thresholds: tuple[str, ...] = (),
        critical_issue_count: int = 0,
        category: str | None = None,
    ):
        super().__init__(message)
        self.decision = decision
        self.metrics = metrics
        self.failed_thresholds = failed_thresholds
        self.critical_issue_count = critical_issue_count
        self.category = category

    @property
    def safe_details(self) -> list[str]:
        details = [f"Final decision: {self.decision.value}."]
        if self.metrics:
            details.extend(
                [
                    f"Groundedness score: {self.metrics.groundedness_score:.4f}.",
                    f"Completeness score: {self.metrics.completeness_score:.4f}.",
                ]
            )
        if self.failed_thresholds:
            details.append(f"Failed thresholds: {', '.join(self.failed_thresholds)}.")
        if self.category:
            details.append(f"Evaluator error category: {self.category}.")
        details.append("PDF artifact was not created.")
        return details
