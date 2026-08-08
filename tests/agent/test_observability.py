import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.observability import (
    EvaluationScore,
    LangfuseObservability,
    safe_provider_response_metadata,
)


class FakePrompt:
    def __init__(self, text: str):
        self.text = text

    def compile(self):
        return self.text


class FakeObservation:
    def __init__(self):
        self.updated_outputs = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def update(self, **kwargs):
        self.updated_outputs.append(kwargs)


class FakeLangfuseClient:
    def __init__(self):
        self.observations = []
        self.prompts = []
        self.scores = []
        self.trace_updates = []
        self.flushed = False
        self.flush_count = 0

    def start_as_current_observation(self, **kwargs):
        observation = FakeObservation()
        self.observations.append((kwargs, observation))
        return observation

    def get_prompt(self, name, **kwargs):
        self.prompts.append({"name": name, **kwargs})
        return FakePrompt("compiled prompt")

    def score_current_trace(self, **kwargs):
        self.scores.append(kwargs)

    def update_current_trace(self, **kwargs):
        self.trace_updates.append(kwargs)

    def flush(self):
        self.flushed = True
        self.flush_count += 1


@contextmanager
def fake_attribute_context(**kwargs):
    yield kwargs


class ObservabilityTest(unittest.TestCase):
    def test_safe_provider_metadata_supports_mapping_and_object_responses(self):
        self.assertEqual(
            safe_provider_response_metadata(
                {
                    "id": "request-1",
                    "choices": [{"finish_reason": "stop"}],
                    "_hidden_params": {"request_id": "ignored"},
                }
            ),
            {"provider_request_id": "request-1", "finish_reason": "stop"},
        )
        self.assertEqual(
            safe_provider_response_metadata(
                SimpleNamespace(
                    choices=[SimpleNamespace(finish_reason="length")],
                    _hidden_params={"request_id": "request-2"},
                )
            ),
            {"provider_request_id": "request-2", "finish_reason": "length"},
        )

    def test_enabled_is_false_when_langfuse_client_is_unavailable(self):
        with patch(
            "jee_tutor.agent.observability.get_client",
            None,
        ):
            observability = LangfuseObservability(LLMConfig({"langfuse": {"enabled": True}}))

        self.assertFalse(observability.enabled)

    def test_disabled_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            observability = LangfuseObservability(LLMConfig({"langfuse": {"enabled": True}}))

            self.assertFalse(observability.enabled)
            with observability.invocation_span(input_payload={}) as span:
                self.assertIsNone(span)

    def test_enabled_flow_records_observations_prompts_scores_and_flushes(self):
        client = FakeLangfuseClient()
        config = LLMConfig(
            {
                "langfuse": {
                    "enabled": True,
                    "trace_name": "trace-name",
                    "generation_name": "generation-name",
                    "flush_after_invocation": True,
                }
            }
        )

        with (
            patch.dict(
                os.environ,
                {
                    "LANGFUSE_PUBLIC_KEY": "public",
                    "LANGFUSE_SECRET_KEY": "secret",
                },
                clear=True,
            ),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
            patch(
                "jee_tutor.agent.observability.propagate_attributes",
                side_effect=fake_attribute_context,
            ),
        ):
            observability = LangfuseObservability(config)
            with observability.invocation_span(
                input_payload={"input": "value"},
                user_id="user",
                session_id="session",
                tags=["tag"],
                metadata={"source": "test"},
            ) as span:
                span.update(output={"ok": True})
            with observability.generation_span(
                model="model",
                input_payload={"messages": "redacted"},
                prompt="prompt-object",
            ) as generation:
                generation.update(output="analysis")
            observability.score_current_trace(
                [EvaluationScore(name="score", value=1, data_type="NUMERIC", comment="ok")]
            )
            observability.publish_deploy_summary(
                name="deploy-summary",
                input_payload={"commit": "abc"},
                output_payload={"pass": True},
                scores=[EvaluationScore(name="deploy", value=True, data_type="BOOLEAN")],
                metadata={"run": "1"},
                tags=["cd"],
            )
            observability.flush()

        self.assertTrue(client.flushed)
        self.assertEqual(len(client.observations), 3)
        self.assertEqual(len(client.scores), 2)
        self.assertEqual(client.trace_updates[-1]["name"], "deploy-summary")

    def test_invocation_flushes_after_parent_span_closes_even_when_legacy_flag_is_false(self):
        events = []
        client = FakeLangfuseClient()

        class TrackingObservation(FakeObservation):
            def __exit__(self, *_args):
                events.append("span_closed")
                return False

        observation = TrackingObservation()
        client.start_as_current_observation = Mock(return_value=observation)
        client.flush = Mock(side_effect=lambda: events.append("flushed"))
        config = LLMConfig(
            {
                "langfuse": {
                    "enabled": True,
                    "flush_after_invocation": False,
                }
            }
        )

        with (
            patch.dict(
                os.environ,
                {
                    "LANGFUSE_PUBLIC_KEY": "public",
                    "LANGFUSE_SECRET_KEY": "secret",
                },
                clear=True,
            ),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
        ):
            with LangfuseObservability(config).invocation_span(input_payload={}):
                events.append("invocation")

        client.flush.assert_called_once_with()
        self.assertEqual(events[-2:], ["span_closed", "flushed"])

    def test_invocation_flushes_when_work_inside_span_raises(self):
        client = FakeLangfuseClient()
        config = LLMConfig({"langfuse": {"enabled": True}})

        with (
            patch.dict(
                os.environ,
                {
                    "LANGFUSE_PUBLIC_KEY": "public",
                    "LANGFUSE_SECRET_KEY": "secret",
                },
                clear=True,
            ),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
            self.assertRaisesRegex(RuntimeError, "invocation failed"),
        ):
            with LangfuseObservability(config).invocation_span(input_payload={}):
                raise RuntimeError("invocation failed")

        self.assertEqual(client.flush_count, 1)

    def test_invocation_start_and_close_failures_are_best_effort(self):
        config = LLMConfig({"langfuse": {"enabled": True}})
        credentials = {
            "LANGFUSE_PUBLIC_KEY": "public",
            "LANGFUSE_SECRET_KEY": "secret",
        }
        with (
            patch.dict(os.environ, credentials, clear=True),
            patch(
                "jee_tutor.agent.observability.get_client",
                side_effect=RuntimeError("initialization failed"),
            ),
            self.assertLogs("jee_tutor.agent.observability", level="WARNING") as logs,
        ):
            with LangfuseObservability(config).invocation_span(input_payload={}) as span:
                self.assertIsNone(span)
        self.assertIn("invocation_start", " ".join(logs.output))

        client = FakeLangfuseClient()
        client.start_as_current_observation = Mock(return_value=RaisingEnterObservation())
        with (
            patch.dict(os.environ, credentials, clear=True),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
            patch(
                "jee_tutor.agent.observability.propagate_attributes",
                return_value=RaisingExitContext(),
            ),
            self.assertLogs("jee_tutor.agent.observability", level="WARNING") as logs,
        ):
            with LangfuseObservability(config).invocation_span(input_payload={}) as span:
                self.assertIsNone(span)
        self.assertIn("invocation_close", " ".join(logs.output))

        client.start_as_current_observation = Mock(return_value=RaisingExitObservation())
        with (
            patch.dict(os.environ, credentials, clear=True),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
            self.assertLogs("jee_tutor.agent.observability", level="WARNING") as logs,
        ):
            with LangfuseObservability(config).invocation_span(input_payload={}) as span:
                self.assertEqual(span.marker, "delegated")
        self.assertIn("invocation_close", " ".join(logs.output))

    def test_provider_body_and_close_failures_preserve_body_error(self):
        client = FakeLangfuseClient()
        client.start_as_current_observation = Mock(return_value=RaisingExitObservation())
        config = LLMConfig({"langfuse": {"enabled": True}})
        with (
            patch.dict(
                os.environ,
                {"LANGFUSE_PUBLIC_KEY": "public", "LANGFUSE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
            self.assertLogs("jee_tutor.agent.observability", level="WARNING") as logs,
            self.assertRaisesRegex(ValueError, "provider body failed"),
        ):
            with LangfuseObservability(config).embedding_span(
                model="gemini/embedding",
                input_payload={},
            ):
                raise ValueError("provider body failed")

        self.assertIn("embedding_close", " ".join(logs.output))

    def test_flush_failure_does_not_fail_invocation(self):
        client = FakeLangfuseClient()
        client.flush = Mock(side_effect=RuntimeError("collector unavailable"))
        config = LLMConfig({"langfuse": {"enabled": True}})

        with (
            patch.dict(
                os.environ,
                {
                    "LANGFUSE_PUBLIC_KEY": "public",
                    "LANGFUSE_SECRET_KEY": "secret",
                },
                clear=True,
            ),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
            self.assertLogs("jee_tutor.agent.observability", level="WARNING") as captured,
        ):
            with LangfuseObservability(config).invocation_span(input_payload={}):
                pass

        self.assertIn("langfuse_flush_failed", " ".join(captured.output))

    def test_score_current_trace_noops_when_disabled_or_empty(self):
        observability = LangfuseObservability(LLMConfig({"langfuse": {"enabled": False}}))
        with patch("jee_tutor.agent.observability.get_client") as get_client:
            observability.score_current_trace([])
            observability.score_current_trace([EvaluationScore(name="score", value=1)])
        get_client.assert_not_called()

    def test_score_without_optional_data_type_and_disabled_flush(self):
        client = FakeLangfuseClient()
        with (
            patch.dict(
                os.environ,
                {"LANGFUSE_PUBLIC_KEY": "public", "LANGFUSE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
        ):
            LangfuseObservability(LLMConfig({})).score_current_trace(
                [EvaluationScore(name="score", value=1)]
            )
        self.assertNotIn("data_type", client.scores[0])

        with patch("jee_tutor.agent.observability.get_client") as get_client:
            LangfuseObservability(
                LLMConfig({"langfuse": {"enabled": False}})
            ).flush()
        get_client.assert_not_called()

    def test_publish_deploy_summary_noops_when_disabled(self):
        observability = LangfuseObservability(LLMConfig({"langfuse": {"enabled": False}}))
        with patch("jee_tutor.agent.observability.get_client") as get_client:
            observability.publish_deploy_summary(
                name="deploy",
                input_payload={"a": 1},
                output_payload={"b": 2},
                scores=[],
            )
        get_client.assert_not_called()

    def test_prompt_fetch_success_returns_compiled_prompt(self):
        client = FakeLangfuseClient()

        with (
            patch.dict(
                os.environ,
                {"LANGFUSE_PUBLIC_KEY": "public", "LANGFUSE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
        ):
            text, prompt = LangfuseObservability(LLMConfig({})).get_text_prompt(
                "prompt-name", "fallback"
            )

        self.assertEqual(text, "compiled prompt")
        self.assertIsInstance(prompt, FakePrompt)

    def test_prompt_fetch_failure_falls_back(self):
        client = FakeLangfuseClient()
        client.get_prompt = Mock(side_effect=RuntimeError("unavailable"))

        with (
            patch.dict(
                os.environ,
                {"LANGFUSE_PUBLIC_KEY": "public", "LANGFUSE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
        ):
            text, prompt = LangfuseObservability(LLMConfig({})).get_text_prompt(
                "prompt-name", "fallback"
            )

        self.assertEqual(text, "fallback")
        self.assertIsNone(prompt)

    def test_provider_trace_initialization_failure_uses_redacted_local_events(self):
        config = LLMConfig({"langfuse": {"enabled": True}})
        with (
            patch.dict(
                os.environ,
                {"LANGFUSE_PUBLIC_KEY": "public", "LANGFUSE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch(
                "jee_tutor.agent.observability.get_client",
                side_effect=RuntimeError("collector unavailable"),
            ),
            self.assertLogs("jee_tutor.agent.observability", level="INFO") as logs,
        ):
            observability = LangfuseObservability(config)
            with observability.generation_span(
                model="gemini/model",
                input_payload={"messages": "secret prompt"},
                metadata={"attempt": 2},
            ) as generation:
                generation.update(output={"status": "succeeded"})
            observability.score_current_trace([EvaluationScore(name="score", value=1)])
            observability.publish_deploy_summary(
                name="summary",
                input_payload={},
                output_payload={},
                scores=[],
            )
            observability.flush()

        joined = " ".join(logs.output)
        self.assertIn("langfuse_operation_failed", joined)
        self.assertIn("llm_provider_attempt_local", joined)
        self.assertIn("llm_provider_result_local", joined)
        self.assertNotIn("secret prompt", joined)

    def test_score_and_deploy_summary_failures_are_best_effort(self):
        client = FakeLangfuseClient()
        client.score_current_trace = Mock(side_effect=RuntimeError("score unavailable"))
        config = LLMConfig({"langfuse": {"enabled": True}})
        credentials = {
            "LANGFUSE_PUBLIC_KEY": "public",
            "LANGFUSE_SECRET_KEY": "secret",
        }
        with (
            patch.dict(os.environ, credentials, clear=True),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
            self.assertLogs("jee_tutor.agent.observability", level="WARNING") as logs,
        ):
            observability = LangfuseObservability(config)
            observability.score_current_trace([EvaluationScore(name="score", value=1)])
        self.assertIn("score_update", " ".join(logs.output))

        client.start_as_current_observation = Mock(return_value=RaisingEnterObservation())
        with (
            patch.dict(os.environ, credentials, clear=True),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
            self.assertLogs("jee_tutor.agent.observability", level="WARNING") as logs,
        ):
            LangfuseObservability(config).publish_deploy_summary(
                name="summary",
                input_payload={},
                output_payload={},
                scores=[],
            )
        self.assertIn("deploy_summary", " ".join(logs.output))

    def test_observation_update_failure_does_not_replace_provider_result(self):
        client = FakeLangfuseClient()
        observation = FakeObservation()
        observation.update = Mock(side_effect=RuntimeError("update unavailable"))
        client.start_as_current_observation = Mock(return_value=observation)
        config = LLMConfig({"langfuse": {"enabled": True}})

        with (
            patch.dict(
                os.environ,
                {"LANGFUSE_PUBLIC_KEY": "public", "LANGFUSE_SECRET_KEY": "secret"},
                clear=True,
            ),
            patch("jee_tutor.agent.observability.get_client", return_value=client),
            self.assertLogs("jee_tutor.agent.observability", level="WARNING") as logs,
        ):
            with LangfuseObservability(config).generation_span(
                model="gemini/model",
                input_payload={},
            ) as generation:
                generation.update(output={"status": "succeeded"})

        self.assertIn("langfuse_operation_failed", " ".join(logs.output))


class RaisingEnterObservation:
    def __enter__(self):
        raise RuntimeError("observation start failed")

    def __exit__(self, *_args):
        return False


class RaisingExitObservation(FakeObservation):
    marker = "delegated"

    def __exit__(self, *_args):
        raise RuntimeError("observation close failed")


class RaisingExitContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        raise RuntimeError("attribute close failed")


if __name__ == "__main__":
    unittest.main()
