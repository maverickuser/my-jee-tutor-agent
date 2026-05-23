import os
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.observability import EvaluationScore, LangfuseObservability


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


@contextmanager
def fake_attribute_context(**kwargs):
    yield kwargs


class ObservabilityTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
