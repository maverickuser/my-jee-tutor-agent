import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from jee_tutor.agent.evaluator_sampling import EvaluatorMode, EvaluatorSamplingPolicy
from jee_tutor.agent.final_evaluation import calculate_metrics, decide_evaluation
from jee_tutor.agent.final_evaluation import FinalEvaluationError
from jee_tutor.agent.workflow import DiagnosisMarkdown
from jee_tutor.invocation.image_inputs import ResolvedImage
from jee_tutor.invocation.service import TutorInvocationService
from tests.agent.test_final_evaluation import assessment, diagnosis


class Observability:
    def invocation_span(self, **kwargs):
        return nullcontext()

    def score_current_trace(self, scores):
        self.scores = scores

    def flush(self):
        pass


class FinalEvaluatorGateTest(unittest.TestCase):
    def service(self, finding, mode=EvaluatorMode.GATED):
        diagnosis_value = diagnosis()
        markdown = DiagnosisMarkdown(
            "| Question Number | Chapter | Topic | What You Thought | "
            "Why That Thought Is Wrong | Exact Concept Gap | What You Must Deep-Dive |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 6 | Mechanics | Friction | likely | wrong | gap | study |",
            diagnosis_value,
        )
        metrics = calculate_metrics(finding, diagnosis_value)
        decision = decide_evaluation(finding, metrics)
        evaluator = Mock()
        evaluator.evaluate.return_value = SimpleNamespace(
            assessment=finding,
            metrics=metrics,
            decision=decision,
            model="gemini/gemini-2.5-flash",
        )
        writer = Mock()
        writer.write_for_invocation.return_value = SimpleNamespace(
            pdf_uri="s3://bucket/report.pdf",
            markdown_uri=None,
            errors=[],
        )
        guardrail = Mock()
        guardrail.check_input.return_value = SimpleNamespace(allowed=True)
        guardrail.check_output.return_value = SimpleNamespace(allowed=True)
        resolver = Mock()
        resolver.resolve_images.return_value = [
            ResolvedImage(data_uri="data:image/png;base64,x", question_number="6")
        ]
        service = TutorInvocationService(
            image_resolver=resolver,
            guardrail=guardrail,
            observability=Observability(),
            workflow=lambda **kwargs: markdown,
            artifact_writer=writer,
            idempotency_store=Mock(),
            final_evaluator=evaluator,
            evaluator_sampling=EvaluatorSamplingPolicy(
                enabled=True,
                sample_rate=1,
                mode=mode,
            ),
        )
        return service, writer

    def test_pass_writes_artifact_once(self):
        service, writer = self.service(assessment(("supported",) * 5))
        response = service.handle(
            {"image_data_uri": "data:image/png;base64,x", "save_analysis_pdf": True}
        )
        self.assertIn("analysis_pdf_uri", response)
        writer.write_for_invocation.assert_called_once()

    def test_review_and_reject_do_not_write_artifact(self):
        for finding in [
            assessment(("supported",) * 4 + ("unsupported",), inference=0.7),
            assessment(("supported", "unsupported"), inference=0.4, satisfied=4),
        ]:
            with self.subTest(statuses=[claim.status for claim in finding.questions[0].claims]):
                service, writer = self.service(finding)
                response = service.handle(
                    {
                        "image_data_uri": "data:image/png;base64,x",
                        "save_analysis_pdf": True,
                    }
                )
                self.assertIn("error", response)
                writer.write_for_invocation.assert_not_called()

    def test_reject_reports_unsatisfied_completeness_fields(self):
        service, writer = self.service(
            assessment(("supported", "unsupported"), inference=0.4, satisfied=5)
        )

        response = service.handle(
            {"image_data_uri": "data:image/png;base64,x", "save_analysis_pdf": True}
        )

        self.assertIn("error", response)
        self.assertIn(
            "Unsatisfied completeness items: row_0.exact_concept_gap, "
            "row_0.what_you_must_deep_dive.",
            response["details"],
        )
        writer.write_for_invocation.assert_not_called()

    def test_shadow_reject_does_not_block_artifact(self):
        service, writer = self.service(
            assessment(("supported", "unsupported"), inference=0.4, satisfied=4),
            mode=EvaluatorMode.SHADOW,
        )
        response = service.handle(
            {"image_data_uri": "data:image/png;base64,x", "save_analysis_pdf": True}
        )
        self.assertIn("analysis_pdf_uri", response)
        writer.write_for_invocation.assert_called_once()

    def test_evaluator_errors_gate_or_fail_open_in_shadow(self):
        for mode, blocked in [
            (EvaluatorMode.GATED, True),
            (EvaluatorMode.SHADOW, False),
        ]:
            service, writer = self.service(assessment())
            service.evaluator_sampling = EvaluatorSamplingPolicy(
                enabled=True,
                sample_rate=1,
                mode=mode,
            )
            service.final_evaluator.evaluate.side_effect = FinalEvaluationError(
                category="evaluator_timeout"
            )
            response = service.handle(
                {"image_data_uri": "data:image/png;base64,x", "save_analysis_pdf": True}
            )
            self.assertEqual("error" in response, blocked)
            self.assertEqual(writer.write_for_invocation.called, not blocked)

    def test_unsampled_diagnosis_bypasses_evaluator(self):
        service, writer = self.service(assessment())
        service.evaluator_sampling = EvaluatorSamplingPolicy(
            enabled=True,
            sample_rate=0,
            mode=EvaluatorMode.GATED,
        )
        response = service.handle(
            {"image_data_uri": "data:image/png;base64,x", "save_analysis_pdf": True}
        )
        self.assertIn("analysis", response)
        service.final_evaluator.evaluate.assert_not_called()
        writer.write_for_invocation.assert_called_once()
