import unittest
from unittest.mock import Mock, patch

from jee_tutor.agent.crew import build_tutor_crew
from jee_tutor.agent.crew_callbacks import CrewCallbackContext, build_crew_callbacks
from jee_tutor.agent.tools import VisionToolCallState


class CrewCallbacksTest(unittest.TestCase):
    def test_build_crew_callbacks_returns_initial_callback_bundle_without_step_callback(self):
        callbacks = build_crew_callbacks(
            CrewCallbackContext(
                invocation_id="inv-1",
                expected_image_count=1,
                expected_question_numbers=["6"],
                tool_call_state=VisionToolCallState(),
            )
        )

        self.assertEqual(len(callbacks.before_kickoff_callbacks), 1)
        self.assertEqual(len(callbacks.after_kickoff_callbacks), 1)
        self.assertIsNotNone(callbacks.task_callback)
        self.assertIsNone(callbacks.step_callback)

    def test_callbacks_emit_safe_metadata_without_full_payloads(self):
        state = VisionToolCallState(
            call_count=2,
            execution_count=1,
            successful_call_count=1,
            cached_replay_count=1,
            observation="secret diagnosis json",
        )
        callbacks = build_crew_callbacks(
            CrewCallbackContext(
                invocation_id="inv-1",
                expected_image_count=1,
                expected_question_numbers=["6"],
                tool_call_state=state,
            )
        )

        with self.assertLogs("jee_tutor.agent.crew_callbacks", level="INFO") as logs:
            callbacks.before_kickoff_callbacks[0](
                {
                    "crew_name": "crew",
                    "task_name": "task",
                    "agent_name": "agent",
                    "image_data_uri": "data:image/png;base64,secret",
                    "recipient_email": "student@example.com",
                }
            )
            callbacks.after_kickoff_callbacks[0](Mock(raw="full diagnosis output"))
            callbacks.task_callback(Mock(raw="invalid output"))

        joined = "\n".join(logs.output)
        self.assertIn("crewai_kickoff_started", joined)
        self.assertIn("crewai_kickoff_completed", joined)
        self.assertIn("crewai_task_completed", joined)
        self.assertIn("output_length=", joined)
        self.assertNotIn("data:image/png", joined)
        self.assertNotIn("student@example.com", joined)
        self.assertNotIn("full diagnosis output", joined)
        self.assertNotIn("invalid output", joined)
        self.assertNotIn("secret diagnosis json", joined)

    def test_hook_logging_failure_does_not_raise(self):
        callbacks = build_crew_callbacks(
            CrewCallbackContext(
                invocation_id="inv-1",
                expected_image_count=1,
                expected_question_numbers=[],
                tool_call_state=VisionToolCallState(),
            )
        )

        with patch("jee_tutor.agent.crew_callbacks.logger.info", side_effect=RuntimeError("log")):
            self.assertEqual(callbacks.before_kickoff_callbacks[0]({}), {})

    def test_callbacks_append_status_events_when_store_is_available(self):
        status_store = Mock()
        state = VisionToolCallState(call_count=1, execution_count=1, successful_call_count=1)
        callbacks = build_crew_callbacks(
            CrewCallbackContext(
                invocation_id="inv-1",
                expected_image_count=1,
                expected_question_numbers=["6"],
                tool_call_state=state,
                status_store=status_store,
            )
        )

        callbacks.before_kickoff_callbacks[0]({})
        callbacks.after_kickoff_callbacks[0](Mock(raw="output"))
        callbacks.task_callback(Mock(raw="output"))

        self.assertEqual(status_store.append_event.call_count, 3)
        event_names = [call.args[1]["event"] for call in status_store.append_event.call_args_list]
        self.assertEqual(event_names, ["CREW_STARTED", "CREW_COMPLETED", "TASK_COMPLETED"])

    def test_build_tutor_crew_wires_callbacks_without_step_callback(self):
        fake_tool = Mock()
        fake_tool.call_state = VisionToolCallState()

        with (
            patch("jee_tutor.agent.crew.PromptProvider"),
            patch("jee_tutor.agent.crew.VisionLLMClient") as llm_client_class,
            patch("jee_tutor.agent.crew.build_vision_tool", return_value=fake_tool),
            patch("jee_tutor.agent.crew.build_tutor_agent", return_value=object()),
            patch("jee_tutor.agent.crew.build_diagnosis_task", return_value=object()),
            patch("jee_tutor.agent.crew.Crew") as crew_class,
        ):
            build_tutor_crew(
                image_data_uris=["data:image/png;base64,x"],
                expected_question_numbers=["6"],
                invocation_id="inv-1",
            )

        self.assertIsNotNone(llm_client_class.return_value)
        _, kwargs = crew_class.call_args
        self.assertEqual(len(kwargs["before_kickoff_callbacks"]), 1)
        self.assertEqual(len(kwargs["after_kickoff_callbacks"]), 1)
        self.assertIsNotNone(kwargs["task_callback"])
        self.assertNotIn("step_callback", kwargs)


if __name__ == "__main__":
    unittest.main()
