import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from jee_tutor.agent.evaluator_client import FinalEvaluator
from jee_tutor.agent.evaluator_crew import (
    build_final_evaluation_task,
    build_final_evaluator_agent,
    build_final_evaluator_crew,
)
from jee_tutor.agent.final_evaluation import FinalDecision, FinalEvaluationError
from jee_tutor.agent.model_config import ModelSettings
from tests.agent.test_final_evaluation import diagnosis


class FakeGeneration:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class FakeObservability:
    def __init__(self, generation=None):
        self.generation = generation
        self.calls = []

    @contextmanager
    def generation_span(self, **kwargs):
        self.calls.append(kwargs)
        yield self.generation


class FakeModelConfig:
    def resolve(self):
        return ModelSettings(
            model="gemini/gemini-2.5-flash",
            api_key="redacted",
            completion_options={"temperature": 0, "timeout": 90},
        )


class ProviderBadRequest(Exception):
    status_code = 400


class EvaluatorClientTest(unittest.TestCase):
    @staticmethod
    def fake_crew(llm):
        crew = Mock()
        crew.kickoff.side_effect = lambda: Mock(raw=llm.call([]))
        return crew

    def test_evaluate_uses_one_structured_redacted_call(self):
        finding = {
            "claims": [
                {
                    "row_index": 0,
                    "field_name": "topic",
                    "claim_kind": "observation",
                    "status": "supported",
                    "evidence_summary": "Visible evidence",
                    "issue_summary": "",
                    "critical": False,
                }
            ],
            "completeness_items": [
                {"row_index": 0, "item_name": name, "satisfied": True}
                for name in (
                    "question_number",
                    "chapter",
                    "topic",
                    "what_you_thought",
                    "why_that_thought_is_wrong",
                    "exact_concept_gap",
                    "what_you_must_deep_dive",
                )
            ],
            "inference_ratings": [
                {
                    "row_index": 0,
                    "criterion_name": "evidence_alignment",
                    "rating": "met",
                }
            ],
            "evaluator_summary": "Supported",
        }
        completion = Mock(return_value={"choices": [{"message": {"content": json.dumps(finding)}}]})
        generation = FakeGeneration()
        observability = FakeObservability(generation)
        evaluator = FinalEvaluator(
            model_config=FakeModelConfig(),
            observability=observability,
            completion_fn=completion,
        )

        with patch(
            "jee_tutor.agent.evaluator_client.build_final_evaluator_crew",
            side_effect=self.fake_crew,
        ):
            result = evaluator.evaluate(
                image_data_uris=["data:image/png;base64,secret"],
                diagnosis=diagnosis(),
                context="fixture",
            )

        self.assertEqual(result.decision.decision, FinalDecision.PASS)
        completion.assert_called_once()
        request = completion.call_args.kwargs
        self.assertEqual(request["model"], "gemini/gemini-2.5-flash")
        self.assertEqual(request["temperature"], 0)
        self.assertEqual(request["num_retries"], 0)
        self.assertEqual(request["response_format"]["type"], "json_schema")
        self.assertNotIn("secret", json.dumps(observability.calls))
        self.assertTrue(generation.updates)

    def test_invalid_and_transport_output_fail_closed(self):
        for output, category in [
            ({"choices": [{"message": {"content": "not json"}}]}, "evaluator_invalid_output"),
            (TimeoutError("provider timeout"), "evaluator_timeout"),
        ]:
            completion = (
                Mock(side_effect=output)
                if isinstance(output, Exception)
                else Mock(return_value=output)
            )
            with self.subTest(category=category):
                evaluator = FinalEvaluator(
                    model_config=FakeModelConfig(),
                    observability=FakeObservability(FakeGeneration()),
                    completion_fn=completion,
                )
                with (
                    patch(
                        "jee_tutor.agent.evaluator_client.build_final_evaluator_crew",
                        side_effect=self.fake_crew,
                    ),
                    self.assertRaises(FinalEvaluationError) as raised,
                ):
                    evaluator.evaluate(
                        image_data_uris=["data:image/png;base64,x"],
                        diagnosis=diagnosis(),
                    )
                self.assertEqual(raised.exception.category, category)

    def test_provider_failure_logs_redacted_detail_and_status(self):
        evaluator = FinalEvaluator(
            model_config=FakeModelConfig(),
            observability=FakeObservability(FakeGeneration()),
            completion_fn=Mock(
                side_effect=ProviderBadRequest("api_key=private schema exceeds complexity limit")
            ),
        )
        with (
            patch(
                "jee_tutor.agent.evaluator_client.build_final_evaluator_crew",
                side_effect=self.fake_crew,
            ),
            self.assertLogs(
                "jee_tutor.agent.evaluator_client",
                level="ERROR",
            ) as captured,
            self.assertRaises(FinalEvaluationError) as raised,
        ):
            evaluator.evaluate(
                image_data_uris=["data:image/png;base64,x"],
                diagnosis=diagnosis(),
            )

        message = " ".join(captured.output)
        self.assertIn("status_code=400", message)
        self.assertIn("schema exceeds complexity limit", message)
        self.assertNotIn("private", message)
        self.assertEqual(raised.exception.category, "evaluator_error")

    def test_invalid_output_logs_safe_validation_locations(self):
        finding = {
            "claims": [
                {
                    "row_index": 0,
                    "field_name": "topic",
                    "claim_kind": "observation",
                    "status": "supported",
                    "evidence_summary": "Visible evidence",
                    "issue_summary": "",
                    "critical": False,
                }
            ],
            "completeness_items": [{"row_index": 0, "item_name": "topic", "satisfied": True}],
            "inference_ratings": [
                {
                    "row_index": 0,
                    "criterion_name": "evidence_alignment",
                    "rating": "sometimes",
                }
            ],
            "evaluator_summary": "Invalid rating",
        }
        evaluator = FinalEvaluator(
            model_config=FakeModelConfig(),
            observability=FakeObservability(FakeGeneration()),
            completion_fn=Mock(
                return_value={"choices": [{"message": {"content": json.dumps(finding)}}]}
            ),
        )
        with (
            patch(
                "jee_tutor.agent.evaluator_client.build_final_evaluator_crew",
                side_effect=self.fake_crew,
            ),
            self.assertLogs(
                "jee_tutor.agent.evaluator_client",
                level="WARNING",
            ) as captured,
            self.assertRaises(FinalEvaluationError),
        ):
            evaluator.evaluate(
                image_data_uris=["data:image/png;base64,x"],
                diagnosis=diagnosis(),
            )

        message = " ".join(captured.output)
        self.assertIn("inference_ratings.0.rating", message)
        self.assertNotIn("Invalid rating", message)

    def test_evaluator_crewai_factories_have_no_tools(self):
        llm = Mock()
        with (
            patch("jee_tutor.agent.evaluator_crew.Agent") as agent_class,
            patch("jee_tutor.agent.evaluator_crew.Task") as task_class,
            patch("jee_tutor.agent.evaluator_crew.Crew") as crew_class,
        ):
            agent = build_final_evaluator_agent(llm)
            task = build_final_evaluation_task(agent)
            build_final_evaluator_crew(llm)

        self.assertEqual(agent_class.call_args.kwargs["tools"], [])
        self.assertFalse(agent_class.call_args.kwargs["allow_delegation"])
        self.assertEqual(task_class.call_args.kwargs["tools"], [])
        self.assertIsNotNone(task)
        self.assertFalse(crew_class.call_args.kwargs["memory"])
