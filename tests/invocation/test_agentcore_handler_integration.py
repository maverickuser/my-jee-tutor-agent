import base64
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from jee_tutor.agent.guardrails import GuardrailCheck
from jee_tutor.handler import handle_tutor_invocation
from jee_tutor.invocation.service import TutorInvocationService


class FakeRuntimeGuardrail:
    def __init__(
        self,
        input_result=None,
        output_result=None,
        calls=None,
    ):
        self.input_result = input_result or GuardrailCheck(allowed=True)
        self.output_result = output_result or GuardrailCheck(allowed=True)
        self.calls = calls if calls is not None else []

    def check_input(self, **kwargs):
        self.calls.append(("input", kwargs))
        return self.input_result

    def check_output(self, analysis):
        self.calls.append(("output", analysis))
        return self.output_result


class FakeArtifactWriter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def write_for_invocation(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class AgentCoreHandlerIntegrationTest(unittest.TestCase):
    def test_successful_invocation_checks_guardrails_around_workflow(self):
        guardrail_calls = []

        with (
            patch(
                "jee_tutor.invocation.service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(calls=guardrail_calls),
            ),
            patch(
                "jee_tutor.invocation.service.run_tutor_workflow",
                return_value="coaching analysis",
            ) as run_tutor_workflow,
        ):
            response = handle_tutor_invocation(
                {
                    "media": {
                        "type": "image",
                        "format": "png",
                        "data": "ZmFrZQ==",
                    },
                    "prompt": "student context",
                }
            )

        self.assertEqual(response, {"analysis": "coaching analysis"})
        run_tutor_workflow.assert_called_once_with(
            image_data_uris=["data:image/png;base64,ZmFrZQ=="],
            question_context="student context",
        )
        self.assertEqual(
            guardrail_calls,
            [
                (
                    "input",
                    {
                        "question_context": "student context",
                        "image_data_uris": ["data:image/png;base64,ZmFrZQ=="],
                    },
                ),
                ("output", "coaching analysis"),
            ],
        )

    def test_agentcore_json_contract_uses_task_and_s3_fields(self):
        image_resolver = Mock()
        image_resolver.resolve.return_value = ["data:image/png;base64,ZmFrZQ=="]
        service = TutorInvocationService(
            image_resolver=image_resolver,
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **kwargs: kwargs["question_context"],
            artifact_writer=FakeArtifactWriter(),
        )

        response = service.handle(
            {
                "task": "diagnose maths attempt",
                "attempt_id": "attempt-123",
                "email": "student@example.com",
                "user_name": "Student Name",
                "subject": "maths",
                "s3_bucket": "attempt-bucket",
                "s3_prefix": "maths/attempt-123/",
                "s3_uri": "s3://attempt-bucket/maths/attempt-123/page-1.png",
                "image_count": 1,
                "source": "web",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response, {"analysis": "diagnose maths attempt"})
        image_resolver.resolve.assert_called_once_with(
            image_data_uri=None,
            image_data_uris=[],
            image_folder=None,
            image_s3_uri="s3://attempt-bucket/maths/attempt-123/page-1.png",
            image_s3_prefix="s3://attempt-bucket/maths/attempt-123/",
            media=None,
        )

    def test_default_invocation_returns_workflow_analysis(self):
        workflow = Mock(return_value="baseline analysis")
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=workflow,
            artifact_writer=FakeArtifactWriter(),
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response, {"analysis": "baseline analysis"})
        self.assertEqual(workflow.call_count, 1)

    def test_folder_invocation_loads_multiple_images(self):
        image_folder = Path(__file__).parents[1] / "fixtures" / "image_folder"
        first_image = (image_folder / "attempt-1.png").read_bytes()
        second_image = (image_folder / "attempt-2.jpg").read_bytes()

        with (
            patch(
                "jee_tutor.invocation.service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(),
            ),
            patch(
                "jee_tutor.invocation.service.run_tutor_workflow",
                return_value="folder analysis",
            ) as run_tutor_workflow,
        ):
            response = handle_tutor_invocation(
                {
                    "image_folder": str(image_folder),
                    "question_context": "multi-page attempt",
                }
            )

        self.assertEqual(response, {"analysis": "folder analysis"})
        run_tutor_workflow.assert_called_once_with(
            image_data_uris=[
                "data:image/png;base64," + base64.b64encode(first_image).decode("ascii"),
                "data:image/jpeg;base64," + base64.b64encode(second_image).decode("ascii"),
            ],
            question_context="multi-page attempt",
        )

    def test_input_guardrail_intervention_skips_workflow(self):
        with (
            patch(
                "jee_tutor.invocation.service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(
                    input_result=GuardrailCheck(
                        allowed=False,
                        message="Input blocked.",
                        action_reason="Denied topic",
                    )
                ),
            ),
            patch("jee_tutor.invocation.service.run_tutor_workflow") as run_tutor_workflow,
        ):
            response = handle_tutor_invocation(
                {
                    "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                    "question_context": "blocked context",
                }
            )

        self.assertEqual(
            response,
            {
                "error": "Input blocked.",
                "details": ["Denied topic"],
            },
        )
        run_tutor_workflow.assert_not_called()

    def test_non_image_media_payload_is_rejected(self):
        with self.assertLogs("jee_tutor.invocation.service", level="INFO") as logs:
            response = handle_tutor_invocation(
                {
                    "media": {
                        "type": "text",
                        "format": "plain",
                        "data": "ZmFrZQ==",
                    },
                    "prompt": "student context",
                }
            )

        self.assertEqual(response["error"], "Invalid tutor invocation payload.")
        self.assertTrue(response["details"])
        self.assertTrue(
            any(
                "agent_invocation metric_name=agent.invocations metric_value=1" in line
                for line in logs.output
            )
        )

    def test_output_guardrail_intervention_replaces_analysis(self):
        with (
            patch(
                "jee_tutor.invocation.service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(
                    output_result=GuardrailCheck(
                        allowed=False,
                        message="Sanitized guardrail response.",
                    )
                ),
            ),
            patch(
                "jee_tutor.invocation.service.run_tutor_workflow",
                return_value="raw unsafe analysis",
            ),
        ):
            response = handle_tutor_invocation(
                {
                    "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                }
            )

        self.assertEqual(response, {"analysis": "Sanitized guardrail response."})

    def test_successful_s3_invocation_returns_pdf_uri(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        artifact_writer = FakeArtifactWriter(
            AnalysisArtifactResult(pdf_uri="s3://attempt-bucket/maths/analysis.pdf")
        )
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=artifact_writer,
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "analysis_pdf_s3_uri": "s3://attempt-bucket/maths/analysis.pdf",
            }
        )

        self.assertEqual(
            response,
            {
                "analysis": "analysis markdown",
                "message": (
                    "Your analysis PDF will be available at "
                    "s3://attempt-bucket/maths/analysis.pdf. "
                    "Please wait 5 minutes before opening it."
                ),
                "pdf_wait_minutes": 5,
                "analysis_pdf_uri": "s3://attempt-bucket/maths/analysis.pdf",
            },
        )
        self.assertEqual(artifact_writer.calls[0]["analysis_markdown"], "analysis markdown")

    def test_pdf_artifact_failure_is_returned_without_dropping_analysis(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=FakeArtifactWriter(
                AnalysisArtifactResult(
                    markdown_uri="s3://attempt-bucket/maths/analysis.md",
                    errors=["Failed to write analysis PDF: RuntimeError: no tex"],
                )
            ),
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "analysis_pdf_s3_uri": "s3://attempt-bucket/maths/analysis.pdf",
            }
        )

        self.assertEqual(response["analysis"], "analysis markdown")
        self.assertEqual(response["analysis_markdown_uri"], "s3://attempt-bucket/maths/analysis.md")
        self.assertEqual(
            response["artifact_errors"],
            ["Failed to write analysis PDF: RuntimeError: no tex"],
        )

    def test_pdf_and_markdown_artifact_failures_keep_analysis(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=FakeArtifactWriter(
                AnalysisArtifactResult(
                    errors=[
                        "Failed to write analysis PDF: RuntimeError: no tex",
                        "Failed to write analysis markdown fallback: RuntimeError: s3 denied",
                    ],
                )
            ),
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "analysis_pdf_s3_uri": "s3://attempt-bucket/maths/analysis.pdf",
            }
        )

        self.assertEqual(response["analysis"], "analysis markdown")
        self.assertNotIn("analysis_pdf_uri", response)
        self.assertNotIn("analysis_markdown_uri", response)
        self.assertEqual(
            response["artifact_errors"],
            [
                "Failed to write analysis PDF: RuntimeError: no tex",
                "Failed to write analysis markdown fallback: RuntimeError: s3 denied",
            ],
        )

    def test_pdf_artifact_can_be_disabled_per_invocation(self):
        from jee_tutor.artifacts.writer import AnalysisArtifactResult

        artifact_writer = FakeArtifactWriter(
            AnalysisArtifactResult(pdf_uri="s3://attempt-bucket/maths/analysis.pdf")
        )
        service = TutorInvocationService(
            guardrail=FakeRuntimeGuardrail(),
            workflow=lambda **_: "analysis markdown",
            artifact_writer=artifact_writer,
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response, {"analysis": "analysis markdown"})
        self.assertEqual(artifact_writer.calls, [])

    def test_workflow_failure_returns_descriptive_error_response(self):
        with self.assertLogs("jee_tutor.invocation.service", level="ERROR") as logs:
            with (
                patch(
                    "jee_tutor.invocation.service.RuntimeGuardrail",
                    return_value=FakeRuntimeGuardrail(),
                ),
                patch(
                    "jee_tutor.invocation.service.run_tutor_workflow",
                    side_effect=RuntimeError("Vision analyzer failed after resolving 1 image(s)."),
                ),
            ):
                response = handle_tutor_invocation(
                    {
                        "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                        "question_context": "diagnose failed attempt",
                    }
                )

        self.assertEqual(response["error"], "Tutor workflow failed while analyzing images.")
        self.assertTrue(any("tutor_workflow_error image_count=1" in line for line in logs.output))
        self.assertIn("Resolved image count: 1.", response["details"])
        self.assertIn("Question context provided: True.", response["details"])
        self.assertIn("Exception type: RuntimeError.", response["details"])
        self.assertIn(
            "Exception message: Vision analyzer failed after resolving 1 image(s).",
            response["details"],
        )

    def test_s3_prefix_images_are_preloaded_for_tool_placeholder_calls(self):
        captured_tool = {}

        def fake_build_tutor_crew(llm_client, prompt_provider, image_data_uris):
            from jee_tutor.agent.llm_client import VisionLLMClient
            from jee_tutor.agent.tools import VisionAnalysisTool

            vision_client = llm_client or VisionLLMClient(completion_fn=completion)
            tool = VisionAnalysisTool(
                llm_client=vision_client,
                preloaded_image_data_uris=image_data_uris or [],
            )
            captured_tool["tool"] = tool

            class FakeCrew:
                def kickoff(self, inputs):
                    self.inputs = inputs
                    return tool._run(["input_file_0.png"], "diagnose")

            return FakeCrew()

        fake_s3_client = Mock()
        fake_s3_client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "maths/page-1.png"}]}
        ]
        fake_s3_client.get_object.return_value = {
            "Body": Mock(read=Mock(return_value=b"s3-image-bytes"))
        }

        with (
            patch(
                "jee_tutor.invocation.service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(),
            ),
            patch.dict("os.environ", {"GOOGLE_API_KEY": "google-key"}),
            patch("jee_tutor.invocation.image_inputs.boto3.client", return_value=fake_s3_client),
            patch("jee_tutor.artifacts.writer.boto3.client", return_value=fake_s3_client),
            patch(
                "jee_tutor.artifacts.writer.PandocPdfRenderer",
                return_value=Mock(render=Mock(return_value=b"%PDF fake report")),
            ),
            patch("jee_tutor.agent.workflow.build_tutor_crew", side_effect=fake_build_tutor_crew),
            patch("jee_tutor.agent.llm_client.completion") as completion,
        ):
            completion.return_value = {"choices": [{"message": {"content": "s3 analysis"}}]}
            response = handle_tutor_invocation(
                {
                    "image_s3_prefix": "s3://attempt-bucket/maths/",
                    "question_context": "diagnose maths attempt",
                }
            )

        self.assertEqual(
            response,
            {
                "analysis": "s3 analysis",
                "message": (
                    "Your analysis PDF will be available at "
                    "s3://attempt-bucket/maths/analysis.pdf. "
                    "Please wait 5 minutes before opening it."
                ),
                "pdf_wait_minutes": 5,
                "analysis_pdf_uri": "s3://attempt-bucket/maths/analysis.pdf",
            },
        )
        messages = completion.call_args.kwargs["messages"]
        image_url = messages[1]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertNotEqual(image_url, "input_file_0.png")
        _, put_kwargs = fake_s3_client.put_object.call_args
        self.assertEqual(put_kwargs["Bucket"], "attempt-bucket")
        self.assertEqual(put_kwargs["Key"], "maths/analysis.pdf")
        self.assertTrue(put_kwargs["Body"].startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
