from __future__ import annotations

import argparse

from eval_runner import run_strict_cases, write_report
from jee_tutor.agent.diagnosis_output import DiagnosisResponse
from jee_tutor.agent.final_evaluation import (
    DIAGNOSIS_FIELD_NAMES,
    EVALUATOR_SCHEMA_VERSION,
    EvaluatorAssessment,
    FinalDecision,
    calculate_metrics,
    decide_evaluation,
    validate_assessment_references,
)
from jee_tutor.agent.model_config import FINAL_EVALUATOR_MODEL


def _diagnosis(number="1"):
    return DiagnosisResponse.model_validate(
        {
            "questions": [
                {
                    "question_number": number,
                    "chapter": "Mechanics",
                    "topic": "Friction",
                    "what_you_thought": "Likely omitted friction",
                    "why_that_thought_is_wrong": "Friction changes acceleration",
                    "exact_concept_gap": "Static friction limit",
                    "what_you_must_deep_dive": "Free-body diagrams",
                }
            ]
        }
    )


def _assessment(
    statuses: tuple[str, ...],
    *,
    satisfied=7,
    inference=1.0,
    critical=False,
    number="1",
):
    return EvaluatorAssessment.model_validate(
        {
            "schema_version": 1,
            "questions": [
                {
                    "row_index": 0,
                    "question_number": number,
                    "claims": [
                        {
                            "row_index": 0,
                            "field_name": "topic",
                            "claim_kind": "observation",
                            "status": status,
                            "evidence_summary": "Fixture evidence",
                            "critical": critical and status == "contradicted",
                        }
                        for status in statuses
                    ],
                    "applicable_completeness_items": list(DIAGNOSIS_FIELD_NAMES),
                    "satisfied_completeness_items": [
                        DIAGNOSIS_FIELD_NAMES[i] for i in range(satisfied)
                    ],
                    "inference_criteria_scores": {"evidence_alignment": inference},
                    "issues": [],
                }
            ],
            "evaluator_summary": "Fixture assessment",
        }
    )


def _case(expected, statuses, **kwargs):
    assessment = _assessment(statuses, **kwargs)
    diagnosis = _diagnosis(kwargs.get("number", "1"))
    validate_assessment_references(assessment, diagnosis)
    metrics = calculate_metrics(assessment, diagnosis)
    decision = decide_evaluation(assessment, metrics)
    return {
        "passed": decision.decision == expected,
        "expected_decision": expected.value,
        "actual_decision": decision.decision.value,
        **metrics.as_dict(),
        "question_count": len(assessment.questions),
        "critical_issue_count": decision.critical_issue_count,
        "artifact_allowed": decision.artifact_allowed,
        "schema_version": EVALUATOR_SCHEMA_VERSION,
        "model": FINAL_EVALUATOR_MODEL,
        "failed_thresholds": list(decision.failed_thresholds),
    }


def wrong_order_case():
    try:
        validate_assessment_references(_assessment(("supported",), number="2"), _diagnosis("1"))
    except Exception as exc:
        return {
            "passed": True,
            "expected_decision": FinalDecision.REJECT.value,
            "actual_decision": FinalDecision.REJECT.value,
            "artifact_allowed": False,
            "schema_version": EVALUATOR_SCHEMA_VERSION,
            "model": FINAL_EVALUATOR_MODEL,
            "reason": type(exc).__name__,
        }
    return {"passed": False, "reason": "Mismatched question reference was accepted."}


CASES = {
    "EVAL-001": lambda: _case(FinalDecision.PASS, ("supported",) * 10),
    "EVAL-002": lambda: _case(
        FinalDecision.REJECT,
        ("supported", "unsupported"),
    ),
    "EVAL-003": lambda: _case(
        FinalDecision.REJECT,
        ("supported", "contradicted"),
        critical=True,
    ),
    "EVAL-004": lambda: _case(FinalDecision.REJECT, ("supported",) * 5, satisfied=4),
    "EVAL-005": lambda: _case(FinalDecision.REJECT, ("supported",) * 5, inference=0.4),
    "EVAL-006": lambda: _case(FinalDecision.PASS, ("supported",) * 5, inference=0.9),
    "EVAL-007": lambda: _case(
        FinalDecision.PASS,
        ("supported",) * 5,
        number="Unreadable from image",
    ),
    "EVAL-008": lambda: _case(
        FinalDecision.REJECT,
        ("supported", "unsupported"),
        number="Unreadable from image",
    ),
    "EVAL-009": lambda: _case(FinalDecision.PASS, ("supported",) * 5),
    "EVAL-010": wrong_order_case,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="eval_runs/final-evaluator-evals.json")
    args = parser.parse_args()
    report = run_strict_cases(CASES)
    write_report(report, args.output)
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
