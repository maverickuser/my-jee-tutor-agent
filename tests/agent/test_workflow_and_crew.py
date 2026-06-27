import unittest
from unittest.mock import Mock, patch

from jee_tutor.agent.crew import build_tutor_crew
from jee_tutor.agent.output_validation import OutputValidationError
from jee_tutor.agent.tools import VisionToolCallState
from jee_tutor.agent.workflow import _validate_vision_tool_call, run_tutor_workflow


VALID_TABLE = """| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | Exact Concept Gap | What You Must Deep-Dive |
| --- | --- | --- | --- | --- | --- | --- |
| 6 | Electrostatics | Capacitors | Used direct formula | Missed charge sharing | Capacitor networks | Charge conservation |
"""


class FakeVisionTool:
    def __init__(self, output=VALID_TABLE, error=None):
        self.output = output
        self.error = error
        self.call_count = 0
        self.state = None

    def run_preloaded(self):
        self.call_count += 1
        if self.error:
            raise self.error
        state = self.state
        state.called = True
        state.success = True
        state.call_count = 1
        state.successful_call_count = 1
        state.image_count = 1
        state.image_source = "preloaded_invocation_images"
        return self.output


class WorkflowAndCrewTest(unittest.TestCase):
    def test_run_tutor_workflow_calls_vision_tool_once_and_validates_output(self):
        llm_client = Mock()
        fake_tool = FakeVisionTool()

        def fake_build_vision_tool(_client, _images, state):
            fake_tool.state = state
            return fake_tool

        with patch(
            "jee_tutor.agent.workflow.build_vision_tool",
            side_effect=fake_build_vision_tool,
        ):
            result = run_tutor_workflow(
                image_data_uri="data:image/png;base64,ZmFrZQ==",
                expected_question_numbers=["6"],
                llm_client=llm_client,
            )

        self.assertEqual(result, VALID_TABLE.strip())
        self.assertEqual(fake_tool.call_count, 1)

    def test_run_tutor_workflow_rejects_missing_images(self):
        with self.assertRaisesRegex(ValueError, "received no images"):
            run_tutor_workflow(llm_client=Mock())

    def test_run_tutor_workflow_preserves_vision_tool_failure(self):
        fake_tool = FakeVisionTool(error=RuntimeError("HTTP 503"))

        with patch(
            "jee_tutor.agent.workflow.build_vision_tool",
            return_value=fake_tool,
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                run_tutor_workflow(
                    image_data_uri="data:image/png;base64,ZmFrZQ==",
                    expected_question_numbers=["6"],
                    llm_client=Mock(),
                )

    def test_run_tutor_workflow_rejects_invalid_markdown(self):
        fake_tool = FakeVisionTool(output="generic answer")

        def fake_build_vision_tool(_client, _images, state):
            fake_tool.state = state
            return fake_tool

        with patch(
            "jee_tutor.agent.workflow.build_vision_tool",
            side_effect=fake_build_vision_tool,
        ):
            with self.assertRaisesRegex(OutputValidationError, "markdown table"):
                run_tutor_workflow(
                    image_data_uri="data:image/png;base64,ZmFrZQ==",
                    expected_question_numbers=["6"],
                    llm_client=Mock(),
                )

    def test_vision_tool_state_validation_rejects_invalid_states(self):
        valid = {
            "called": True,
            "success": True,
            "call_count": 1,
            "successful_call_count": 1,
            "image_count": 1,
            "image_source": "preloaded_invocation_images",
        }
        invalid_states = [
            ({**valid, "called": False}, "did not call"),
            ({**valid, "call_count": 2}, "exactly once"),
            ({**valid, "success": False}, "did not complete successfully"),
            ({**valid, "successful_call_count": 0}, "successfully exactly once"),
            ({**valid, "image_source": "tool_input_data_uris"}, "preloaded"),
            ({**valid, "image_count": 2}, "image count"),
        ]

        for values, message in invalid_states:
            with self.subTest(message=message):
                with self.assertRaisesRegex(OutputValidationError, message):
                    _validate_vision_tool_call(VisionToolCallState(**values), 1)

    def test_build_tutor_crew_wires_agent_task_and_tool(self):
        fake_tool = object()
        fake_agent = object()
        fake_task = object()

        with (
            patch("jee_tutor.agent.crew.PromptProvider") as prompt_provider_class,
            patch("jee_tutor.agent.crew.VisionLLMClient") as llm_client_class,
            patch("jee_tutor.agent.crew.build_vision_tool", return_value=fake_tool) as build_tool,
            patch("jee_tutor.agent.crew.build_tutor_agent", return_value=fake_agent) as build_agent,
            patch(
                "jee_tutor.agent.crew.build_diagnosis_task",
                return_value=fake_task,
            ) as build_task,
            patch("jee_tutor.agent.crew.Crew") as crew_class,
        ):
            prompts = prompt_provider_class.return_value
            llm_client = llm_client_class.return_value
            build_tutor_crew(image_data_uris=["data:image/png;base64,ZmFrZQ=="])

        llm_client_class.assert_called_once_with(prompt_provider=prompts)
        build_tool.assert_called_once_with(llm_client, ["data:image/png;base64,ZmFrZQ=="], None)
        build_agent.assert_called_once_with(fake_tool, prompts)
        build_task.assert_called_once_with(fake_agent, fake_tool, prompts)
        crew_class.assert_called_once()
        _, kwargs = crew_class.call_args
        self.assertEqual(kwargs["agents"], [fake_agent])
        self.assertEqual(kwargs["tasks"], [fake_task])
        self.assertTrue(kwargs["verbose"])
        self.assertIsNotNone(llm_client)


if __name__ == "__main__":
    unittest.main()
