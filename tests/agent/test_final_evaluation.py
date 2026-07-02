import unittest
from unittest.mock import patch
from pydantic import ValidationError

from jee_tutor.agent.diagnosis_output import DiagnosisResponse
from jee_tutor.agent.final_evaluation import (
    DIAGNOSIS_FIELD_NAMES,
    EvaluationCalculationError,
    EvaluationThresholds,
    EvaluatorAssessment,
    EvaluatorTransportAssessment,
    FinalDecision,
    build_evaluator_assessment,
    calculate_metrics,
    decide_evaluation,
    evaluator_response_format,
    validate_assessment_references,
    FinalEvaluationError,
)
from jee_tutor.agent.config_loader import LLMConfig


def diagnosis():
    return DiagnosisResponse.model_validate(
        {
            "questions": [
                {
                    "question_number": "6",
                    "chapter": "Mechanics",
                    "topic": "Friction",
                    "what_you_thought": "Likely ignored friction",
                    "why_that_thought_is_wrong": "Friction changes acceleration",
                    "exact_concept_gap": "Static friction limit",
                    "what_you_must_deep_dive": "Free-body diagrams",
                }
            ]
        }
    )


def assessment(statuses=("supported",), inference=1.0, satisfied=7, critical=False):
    return EvaluatorAssessment.model_validate(
        {
            "schema_version": 1,
            "questions": [
                {
                    "row_index": 0,
                    "question_number": "6",
                    "claims": [
                        {
                            "row_index": 0,
                            "field_name": "topic",
                            "claim_kind": "observation",
                            "status": status,
                            "evidence_summary": "Visible evidence",
                            "critical": critical,
                        }
                        for status in statuses
                    ],
                    "applicable_completeness_items": list(DIAGNOSIS_FIELD_NAMES),
                    "satisfied_completeness_items": [
                        DIAGNOSIS_FIELD_NAMES[i] for i in range(satisfied)
                    ],
                    "inference_criteria_scores": [
                        {"name": "evidence_alignment", "score": inference}
                    ],
                    "issues": [],
                }
            ],
            "evaluator_summary": "Bounded summary",
        }
    )


class FinalEvaluationTest(unittest.TestCase):
    def test_metrics_use_mutually_exclusive_claim_counts(self):
        metrics = calculate_metrics(
            assessment(("supported", "unsupported", "contradicted"), 0.8, 6),
            diagnosis(),
        )
        self.assertEqual(metrics.groundedness_score, 0.3333)
        self.assertEqual(metrics.unsupported_claim_rate, 0.3333)
        self.assertEqual(metrics.contradiction_rate, 0.3333)
        self.assertEqual(metrics.completeness_score, 0.8571)
        self.assertEqual(metrics.inference_quality_score, 0.8)

    def test_exact_pass_boundaries_pass(self):
        metrics = calculate_metrics(assessment(), diagnosis())
        result = decide_evaluation(metrics=metrics, assessment=assessment())
        self.assertEqual(result.decision, FinalDecision.PASS)

    def test_review_and_reject_policy(self):
        review_assessment = assessment(
            ("supported", "supported", "supported", "supported", "unsupported"),
            0.7,
            6,
        )
        review = decide_evaluation(
            review_assessment,
            calculate_metrics(review_assessment, diagnosis()),
        )
        self.assertEqual(review.decision, FinalDecision.REVIEW)

        reject_assessment = assessment(("supported", "unsupported"), 0.5, 4)
        reject = decide_evaluation(
            reject_assessment,
            calculate_metrics(reject_assessment, diagnosis()),
        )
        self.assertEqual(reject.decision, FinalDecision.REJECT)

    def test_critical_contradiction_rejects(self):
        finding = assessment(("supported", "contradicted"), critical=True)
        result = decide_evaluation(finding, calculate_metrics(finding, diagnosis()))
        self.assertEqual(result.decision, FinalDecision.REJECT)
        self.assertIn("critical_contradiction", result.failed_thresholds)

    def test_invalid_thresholds_and_missing_inference_fail_closed(self):
        with self.assertRaises(ValueError):
            EvaluationThresholds(pass_groundedness_score=float("nan"))
        finding = assessment()
        finding.questions[0].inference_criteria_scores = []
        with self.assertRaises(EvaluationCalculationError):
            calculate_metrics(finding, diagnosis())

    def test_threshold_config_reference_validation_and_safe_error(self):
        thresholds = EvaluationThresholds.from_config(
            LLMConfig({"final_evaluator": {"pass_groundedness_score": 0.95}})
        )
        self.assertEqual(thresholds.pass_groundedness_score, 0.95)
        with self.assertRaises(ValueError):
            EvaluationThresholds(pass_groundedness_score=0.5)

        mismatched = assessment()
        mismatched.questions[0].question_number = "7"
        with self.assertRaises(EvaluationCalculationError):
            validate_assessment_references(mismatched, diagnosis())

        valid_metrics = calculate_metrics(assessment(), diagnosis())
        error = FinalEvaluationError(
            decision=FinalDecision.REVIEW,
            metrics=valid_metrics,
            failed_thresholds=("groundedness_score",),
            category="fixture",
        )
        self.assertIn("Groundedness score", " ".join(error.safe_details))
        self.assertIn("fixture", " ".join(error.safe_details))

    def test_invalid_assessment_references_fail_schema_validation(self):
        base = assessment().model_dump()
        invalid_mutations = [
            lambda value: value["questions"][0]["claims"][0].update(row_index=1),
            lambda value: value["questions"][0].update(
                applicable_completeness_items=["a", "a"],
                satisfied_completeness_items=[],
            ),
            lambda value: value["questions"][0].update(
                applicable_completeness_items=["a"],
                satisfied_completeness_items=["b"],
            ),
            lambda value: value["questions"][0].update(
                inference_criteria_scores=[{"name": "", "score": 1.0}]
            ),
            lambda value: value["questions"][0].update(
                inference_criteria_scores=[
                    {"name": "evidence_alignment", "score": 1.0},
                    {"name": "evidence_alignment", "score": 0.5},
                ]
            ),
        ]
        for mutate in invalid_mutations:
            payload = assessment().model_dump()
            mutate(payload)
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                EvaluatorAssessment.model_validate(payload)
        self.assertTrue(base)

    def test_provider_schema_is_flat_and_omits_non_semantic_metadata(self):
        response_format = evaluator_response_format()
        schema = response_format["json_schema"]["schema"]
        self.assertEqual(
            set(schema["properties"]),
            {"claims", "completeness_items", "inference_scores", "evaluator_summary"},
        )
        for definition in schema["$defs"].values():
            for property_schema in definition.get("properties", {}).values():
                self.assertNotEqual(property_schema.get("type"), "array")
        encoded = str(schema)
        for keyword in ("additionalProperties", "default", "maxItems", "title"):
            self.assertNotIn(keyword, encoded)

    def test_flat_provider_assessment_converts_to_domain_assessment(self):
        transport = EvaluatorTransportAssessment.model_validate(
            {
                "claims": [
                    {
                        "row_index": 0,
                        "field_name": "topic",
                        "claim_kind": "observation",
                        "status": "supported",
                        "evidence_summary": "Visible mechanics question",
                        "issue_summary": "",
                        "critical": False,
                    }
                ],
                "completeness_items": [
                    {
                        "row_index": 0,
                        "item_name": field_name,
                        "satisfied": True,
                    }
                    for field_name in DIAGNOSIS_FIELD_NAMES
                ],
                "inference_scores": [
                    {
                        "row_index": 0,
                        "criterion_name": "evidence_alignment",
                        "score": 1.0,
                    }
                ],
                "evaluator_summary": "Supported",
            }
        )
        converted = build_evaluator_assessment(transport, diagnosis())
        validate_assessment_references(converted, diagnosis())
        self.assertEqual(converted.questions[0].question_number, "6")
        self.assertEqual(
            calculate_metrics(converted, diagnosis()).groundedness_score,
            1.0,
        )

    def test_zero_denominators_unreadable_and_consistency_fail_closed(self):
        no_claims = assessment()
        no_claims.questions[0].claims = []
        with self.assertRaisesRegex(EvaluationCalculationError, "no classifiable"):
            calculate_metrics(no_claims, diagnosis())

        no_items = assessment()
        no_items.questions[0].applicable_completeness_items = []
        no_items.questions[0].satisfied_completeness_items = []
        with self.assertRaisesRegex(EvaluationCalculationError, "no applicable"):
            calculate_metrics(no_items, diagnosis())

        unreadable_diagnosis = diagnosis()
        unreadable_diagnosis.questions[0].question_number = "Unreadable from image"
        no_inference = assessment()
        no_inference.questions[0].question_number = "Unreadable from image"
        no_inference.questions[0].inference_criteria_scores = []
        self.assertEqual(
            calculate_metrics(no_inference, unreadable_diagnosis).inference_quality_score,
            1.0,
        )

        with (
            patch("jee_tutor.agent.final_evaluation.math.isclose", return_value=False),
            self.assertRaisesRegex(EvaluationCalculationError, "inconsistent"),
        ):
            calculate_metrics(assessment(), diagnosis())
