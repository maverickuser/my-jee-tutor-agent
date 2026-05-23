import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.model_config import VisionModelConfig
from jee_tutor.agent.prompt_provider import PromptProvider


class RecordingGeneration:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class RecordingObservability:
    def __init__(self):
        self.generation = RecordingGeneration()

    @contextmanager
    def generation_span(self, **kwargs):
        yield self.generation

    def get_text_prompt(self, name, fallback):
        return fallback, None


class LLMClientAccountingTest(unittest.TestCase):
    def test_updates_langfuse_generation_with_usage_and_cost_details(self):
        config = LLMConfig(
            {
                "vision": {"model": "gemini/gemini-3-flash-preview"},
                "completion": {"temperature": 0.2},
            }
        )
        observability = RecordingObservability()
        prompt_provider = PromptProvider(config=config, observability=observability)
        model_config = VisionModelConfig(
            environ={"GOOGLE_API_KEY": "google-key"},
            config=config,
        )
        completion = Mock(
            return_value={
                "choices": [{"message": {"content": "analysis"}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 25,
                    "total_tokens": 125,
                },
                "_hidden_params": {"response_cost": 0.00042},
            }
        )
        client = VisionLLMClient(
            model_config=model_config,
            observability=observability,
            prompt_provider=prompt_provider,
            completion_fn=completion,
        )

        with patch("jee_tutor.agent.llm_client.gemini_rate_limiter") as limiter:
            limiter.call.side_effect = lambda func, **kwargs: func(**kwargs)

            self.assertEqual(
                client.analyze_vision("data:image/png;base64,AA==", "prompt"),
                "analysis",
            )

        self.assertEqual(
            observability.generation.updates,
            [
                {
                    "output": "analysis",
                    "usage_details": {
                        "prompt_tokens": 100,
                        "completion_tokens": 25,
                        "total_tokens": 125,
                    },
                    "cost_details": {"total": 0.00042},
                }
            ],
        )

    def test_accounting_omits_cost_when_litellm_cannot_infer_it(self):
        response = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 25,
                "total_tokens": 125,
            }
        }

        with patch("jee_tutor.agent.llm_client.completion_cost", side_effect=Exception("unknown")):
            accounting = VisionLLMClient._generation_accounting(response, "gemini/unknown")

        self.assertEqual(
            accounting,
            {
                "usage_details": {
                    "prompt_tokens": 100,
                    "completion_tokens": 25,
                    "total_tokens": 125,
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
