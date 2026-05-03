import base64
import unittest
from pathlib import Path
from unittest.mock import patch

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
                "agentcore_handler.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(calls=guardrail_calls),
            ),
            patch(
                "agentcore_handler.run_tutor_workflow",
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
                "agentcore_handler.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(),
            ),
            patch(
                "agentcore_handler.run_tutor_workflow",
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
                "agentcore_handler.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(
                    input_result=GuardrailCheck(
                        allowed=False,
                        message="Input blocked.",
                        action_reason="Denied topic",
                    )
                ),
            ),
            patch("agentcore_handler.run_tutor_workflow") as run_tutor_workflow,
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

    def test_output_guardrail_intervention_replaces_analysis(self):
        with (
            patch(
                "agentcore_handler.RuntimeGuardrail",
                return_value=FakeRuntimeGuardrail(
                    output_result=GuardrailCheck(
                        allowed=False,
                        message="Sanitized guardrail response.",
                    )
                ),
            ),
            patch(
                "agentcore_handler.run_tutor_workflow",
                return_value="raw unsafe analysis",
            ),
        ):
            response = handle_tutor_invocation(
                {
                    "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                }
            )

        self.assertEqual(response, {"analysis": "Sanitized guardrail response."})


if __name__ == "__main__":
    unittest.main()
