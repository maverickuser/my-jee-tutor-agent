import os
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from jee_tutor.agent.final_evaluation import FinalDecision
from jee_tutor.invocation.image_inputs import ResolvedImage
from scripts.run_live_final_evaluator_evals import (
    build_incomplete_diagnosis,
    build_unsupported_diagnosis,
    run_live_evaluator_cases,
)


class Metrics:
    def __init__(
        self,
        *,
        unsupported_claim_rate: float,
        contradiction_rate: float,
        completeness_score: float,
    ):
        self.values = {
            "groundedness_score": 0.0,
            "unsupported_claim_rate": unsupported_claim_rate,
            "contradiction_rate": contradiction_rate,
            "completeness_score": completeness_score,
            "inference_quality_score": 0.0,
            "supported_claim_count": 0,
            "unsupported_claim_count": 1,
            "contradicted_claim_count": 0,
            "total_claim_count": 1,
        }

    def as_dict(self):
        return self.values


class FakeObservation:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeObservability:
    def invocation_span(self, **_kwargs):
        return FakeObservation()


def _result(*, unsupported: float, completeness: float):
    return SimpleNamespace(
        assessment=SimpleNamespace(questions=[object(), object(), object()]),
        metrics=Metrics(
            unsupported_claim_rate=unsupported,
            contradiction_rate=0.0,
            completeness_score=completeness,
        ),
        decision=SimpleNamespace(
            decision=FinalDecision.REJECT,
            artifact_allowed=False,
            failed_thresholds=("fixture_threshold",),
        ),
        model="gemini/gemini-2.5-flash",
    )


class LiveFinalEvaluatorEvalsTest(unittest.TestCase):
    def setUp(self):
        self.images = [
            ResolvedImage(
                data_uri=f"data:image/png;base64,image-{index}", question_number=str(index)
            )
            for index in range(1, 4)
        ]

    def test_fixture_diagnoses_have_one_row_per_image(self):
        unsupported = build_unsupported_diagnosis(self.images)
        incomplete = build_incomplete_diagnosis(self.images)

        self.assertEqual(len(unsupported.questions), 3)
        self.assertEqual(len(incomplete.questions), 3)
        self.assertIn("CD_UNSUPPORTED_SENTINEL_1", unsupported.questions[0].what_you_thought)
        self.assertEqual(incomplete.questions[0].topic, "Not provided in this diagnosis.")

    def test_script_can_run_without_pythonpath(self):
        repo_root = Path(__file__).resolve().parents[2]
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)

        result = subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "run_live_final_evaluator_evals.py"),
                "--help",
            ],
            cwd=repo_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--image-s3-prefix", result.stdout)

    def test_suite_makes_exactly_two_evaluator_calls_and_passes_both_rejections(self):
        evaluator = Mock()
        evaluator.evaluate.side_effect = [
            _result(unsupported=1.0, completeness=1.0),
            _result(unsupported=0.0, completeness=0.0),
        ]

        report = run_live_evaluator_cases(
            self.images,
            evaluator=evaluator,
            observability=FakeObservability(),
        )

        self.assertTrue(report["gate_passed"])
        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["passed_count"], 2)
        self.assertEqual(evaluator.evaluate.call_count, 2)

    def test_suite_fails_when_flash_accepts_negative_diagnosis(self):
        accepted = _result(unsupported=0.0, completeness=1.0)
        accepted.decision.decision = FinalDecision.PASS
        accepted.decision.artifact_allowed = True
        evaluator = Mock()
        evaluator.evaluate.side_effect = [
            accepted,
            _result(unsupported=0.0, completeness=0.0),
        ]

        report = run_live_evaluator_cases(
            self.images,
            evaluator=evaluator,
            observability=FakeObservability(),
        )

        self.assertFalse(report["gate_passed"])
        self.assertFalse(report["cases"][0]["passed"])


if __name__ == "__main__":
    unittest.main()
