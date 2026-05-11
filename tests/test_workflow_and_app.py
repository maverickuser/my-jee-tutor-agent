import unittest
from unittest.mock import patch

from agentcore_handler import validate_tutor_invocation
from agents.tutor_agent.crew import build_tutor_crew
from agents.tutor_agent.workflow import DEFAULT_QUESTION_CONTEXT, run_tutor_workflow


class FakeCrew:
    def __init__(self):
        self.inputs = None

    def kickoff(self, inputs):
        self.inputs = inputs
        return "  final analysis  "


class WorkflowAndAppTest(unittest.TestCase):
    def test_validate_tutor_invocation_returns_model(self):
        payload = validate_tutor_invocation({"image_data_uri": "data:image/png;base64,ZmFrZQ=="})

        self.assertEqual(payload.image_data_uri, "data:image/png;base64,ZmFrZQ==")

    def test_run_tutor_workflow_uses_single_image_and_default_context(self):
        crew = FakeCrew()

        with patch("agents.tutor_agent.workflow.build_tutor_crew", return_value=crew) as build_crew:
            result = run_tutor_workflow(image_data_uri="data:image/png;base64,ZmFrZQ==")

        self.assertEqual(result, "final analysis")
        build_crew.assert_called_once_with(
            None,
            None,
            ["data:image/png;base64,ZmFrZQ=="],
        )
        self.assertEqual(
            crew.inputs,
            {
                "image_data_uris": "[preloaded in vision tool]",
                "image_count": 1,
                "question_context": DEFAULT_QUESTION_CONTEXT,
            },
        )

    def test_build_tutor_crew_wires_agent_task_and_tool(self):
        fake_tool = object()
        fake_agent = object()
        fake_task = object()

        with (
            patch("agents.tutor_agent.crew.PromptProvider") as prompt_provider_class,
            patch("agents.tutor_agent.crew.VisionLLMClient") as llm_client_class,
            patch(
                "agents.tutor_agent.crew.build_vision_tool", return_value=fake_tool
            ) as build_tool,
            patch("agents.tutor_agent.crew.build_tutor_agent", return_value=fake_agent),
            patch("agents.tutor_agent.crew.build_diagnosis_task", return_value=fake_task),
            patch("agents.tutor_agent.crew.Crew") as crew_class,
        ):
            prompts = prompt_provider_class.return_value
            llm_client = llm_client_class.return_value
            build_tutor_crew(image_data_uris=["data:image/png;base64,ZmFrZQ=="])

        llm_client_class.assert_called_once_with(prompt_provider=prompts)
        build_tool.assert_called_once_with(llm_client, ["data:image/png;base64,ZmFrZQ=="])
        crew_class.assert_called_once()
        _, kwargs = crew_class.call_args
        self.assertEqual(kwargs["agents"], [fake_agent])
        self.assertEqual(kwargs["tasks"], [fake_task])
        self.assertTrue(kwargs["verbose"])
        self.assertIsNotNone(llm_client)

    def test_agentcore_app_entrypoint_delegates_to_handler(self):
        with patch("agentcore_app.handle_tutor_invocation", return_value={"analysis": "ok"}):
            from agentcore_app import invoke_tutor

            self.assertEqual(invoke_tutor({"image_data_uri": "x"}, None), {"analysis": "ok"})


if __name__ == "__main__":
    unittest.main()
