import unittest
from unittest.mock import Mock, patch

from jee_tutor.agent.crew import build_tutor_crew
from jee_tutor.agent.output_validation import OutputValidationError
from jee_tutor.agent.workflow import run_tutor_workflow


VALID_TABLE = """| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | Exact Concept Gap | What You Must Deep-Dive |
| --- | --- | --- | --- | --- | --- | --- |
| 6 | Electrostatics | Capacitors | Used direct formula | Missed charge sharing | Capacitor networks | Charge conservation |
"""


class FakeCrew:
    def __init__(self, output=VALID_TABLE, mark_tool_success=True):
        self.output = output
        self.mark_tool_success = mark_tool_success
        self.inputs = None

    def kickoff(self, inputs):
        self.inputs = inputs
        if self.mark_tool_success:
            state = self.tool_call_state
            state.called = True
            state.success = True
            state.image_count = 1
            state.image_source = "preloaded_invocation_images"
        return self.output


class WorkflowAndCrewTest(unittest.TestCase):
    def test_run_tutor_workflow_uses_crewai_and_validates_output(self):
        llm_client = Mock()
        fake_crew = FakeCrew()

        def fake_build_tutor_crew(**kwargs):
            fake_crew.tool_call_state = kwargs["tool_call_state"]
            return fake_crew

        with patch("jee_tutor.agent.workflow.build_tutor_crew", side_effect=fake_build_tutor_crew):
            result = run_tutor_workflow(
                image_data_uri="data:image/png;base64,ZmFrZQ==",
                expected_question_numbers=["6"],
                llm_client=llm_client,
            )

        self.assertEqual(result, VALID_TABLE.strip())
        self.assertEqual(
            fake_crew.inputs,
            {
                "image_data_uris": "[preloaded in vision tool]",
                "image_count": 1,
                "question_context": "No additional context provided.",
            },
        )

    def test_run_tutor_workflow_rejects_missing_images(self):
        with self.assertRaisesRegex(ValueError, "received no images"):
            run_tutor_workflow(llm_client=Mock())

    def test_run_tutor_workflow_rejects_when_crewai_does_not_call_vision_tool(self):
        fake_crew = FakeCrew(mark_tool_success=False)

        def fake_build_tutor_crew(**kwargs):
            fake_crew.tool_call_state = kwargs["tool_call_state"]
            return fake_crew

        with patch("jee_tutor.agent.workflow.build_tutor_crew", side_effect=fake_build_tutor_crew):
            with self.assertRaisesRegex(OutputValidationError, "did not call"):
                run_tutor_workflow(
                    image_data_uri="data:image/png;base64,ZmFrZQ==",
                    expected_question_numbers=["6"],
                    llm_client=Mock(),
                )

    def test_run_tutor_workflow_rejects_invalid_markdown(self):
        fake_crew = FakeCrew(output="generic answer")

        def fake_build_tutor_crew(**kwargs):
            fake_crew.tool_call_state = kwargs["tool_call_state"]
            return fake_crew

        with patch("jee_tutor.agent.workflow.build_tutor_crew", side_effect=fake_build_tutor_crew):
            with self.assertRaisesRegex(OutputValidationError, "markdown table"):
                run_tutor_workflow(
                    image_data_uri="data:image/png;base64,ZmFrZQ==",
                    expected_question_numbers=["6"],
                    llm_client=Mock(),
                )

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
