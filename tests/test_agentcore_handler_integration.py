import base64
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agents.tutor_agent.guardrails import GuardrailCheck
from agentcore_handler import handle_tutor_invocation


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


class AgentCoreHandlerIntegrationTest(unittest.TestCase):
    def test_successful_invocation_checks_guardrails_around_workflow(self):
        guardrail_calls = []

        with (
            patch(
                "tutor_invocation_service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(calls=guardrail_calls),
            ),
            patch(
                "tutor_invocation_service.run_tutor_workflow",
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

    def test_folder_invocation_loads_multiple_images(self):
        image_folder = Path(__file__).parent / "fixtures" / "image_folder"
        first_image = (image_folder / "attempt-1.png").read_bytes()
        second_image = (image_folder / "attempt-2.jpg").read_bytes()

        with (
            patch(
                "tutor_invocation_service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(),
            ),
            patch(
                "tutor_invocation_service.run_tutor_workflow",
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
                "tutor_invocation_service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(
                    input_result=GuardrailCheck(
                        allowed=False,
                        message="Input blocked.",
                        action_reason="Denied topic",
                    )
                ),
            ),
            patch("tutor_invocation_service.run_tutor_workflow") as run_tutor_workflow,
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

    def test_output_guardrail_intervention_replaces_analysis(self):
        with (
            patch(
                "tutor_invocation_service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(
                    output_result=GuardrailCheck(
                        allowed=False,
                        message="Sanitized guardrail response.",
                    )
                ),
            ),
            patch(
                "tutor_invocation_service.run_tutor_workflow",
                return_value="raw unsafe analysis",
            ),
        ):
            response = handle_tutor_invocation(
                {
                    "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                }
            )

        self.assertEqual(response, {"analysis": "Sanitized guardrail response."})

    def test_workflow_failure_returns_descriptive_error_response(self):
        with (
            patch(
                "tutor_invocation_service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(),
            ),
            patch(
                "tutor_invocation_service.run_tutor_workflow",
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
            from agents.tutor_agent.llm_client import VisionLLMClient
            from agents.tutor_agent.tools import VisionAnalysisTool

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
                "tutor_invocation_service.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(),
            ),
            patch.dict("os.environ", {"GOOGLE_API_KEY": "google-key"}),
            patch("image_inputs.boto3.client", return_value=fake_s3_client),
            patch(
                "agents.tutor_agent.workflow.build_tutor_crew", side_effect=fake_build_tutor_crew
            ),
            patch("agents.tutor_agent.llm_client.completion") as completion,
        ):
            completion.return_value = {"choices": [{"message": {"content": "s3 analysis"}}]}
            response = handle_tutor_invocation(
                {
                    "image_s3_prefix": "s3://attempt-bucket/maths/",
                    "question_context": "diagnose maths attempt",
                }
            )

        self.assertEqual(response, {"analysis": "s3 analysis"})
        messages = completion.call_args.kwargs["messages"]
        image_url = messages[1]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertNotEqual(image_url, "input_file_0.png")


if __name__ == "__main__":
    unittest.main()
