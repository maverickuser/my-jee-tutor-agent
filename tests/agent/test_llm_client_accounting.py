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


class UsageModel:
    def model_dump(self, exclude_none=False):
        return {
            "prompt_tokens": 10,
            "completion_tokens": None,
            "total_tokens": 12,
        }


class TokenDetailModel:
    def model_dump(self, exclude_none=False):
        values = {"cached_tokens": 3, "audio_tokens": None}
        if exclude_none:
            return {key: value for key, value in values.items() if value is not None}
        return values


class UsageObject:
    def __init__(self):
        self.prompt_tokens = 10
        self.completion_tokens = None
        self.total_tokens = 12
        self.prompt_tokens_details = TokenDetailObject()
        self._private = "hidden"


class TokenDetailObject:
    def __init__(self):
        self.cached_tokens = 3
        self.audio_tokens = None
        self._private = "hidden"


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

    def test_non_gemini_completion_bypasses_rate_limiter_and_handles_no_generation(self):
        config = LLMConfig(
            {
                "vision": {"model": "openai/gpt-4o"},
                "completion": {"temperature": 0.2},
            }
        )
        observability = RecordingObservability()
        prompt_provider = PromptProvider(config=config, observability=observability)
        model_config = VisionModelConfig(
            environ={"OPENAI_API_KEY": "openai-key"},
            config=config,
        )
        completion = Mock(return_value={"choices": [{"message": {"content": " analysis "}}]})
        client = VisionLLMClient(
            model_config=model_config,
            observability=observability,
            prompt_provider=prompt_provider,
            completion_fn=completion,
        )

        @contextmanager
        def no_generation_span(**kwargs):
            yield None

        observability.generation_span = no_generation_span

        with patch("jee_tutor.agent.llm_client.gemini_rate_limiter") as limiter:
            self.assertEqual(
                client.analyze_vision("data:image/png;base64,AA==", "prompt"),
                "analysis",
            )

        completion.assert_called_once()
        limiter.call.assert_not_called()

    def test_accounting_is_empty_without_usage_or_cost(self):
        with patch("jee_tutor.agent.llm_client.completion_cost", return_value=None):
            self.assertEqual(VisionLLMClient._generation_accounting({}, "model"), {})

    def test_usage_details_compact_pydantic_like_models(self):
        response = {"usage": UsageModel()}

        self.assertEqual(
            VisionLLMClient._usage_details(response),
            {
                "prompt_tokens": 10,
                "total_tokens": 12,
            },
        )

    def test_usage_details_compact_plain_objects_and_nested_details(self):
        response = type("Response", (), {"usage": UsageObject()})()

        self.assertEqual(
            VisionLLMClient._usage_details(response),
            {
                "prompt_tokens": 10,
                "total_tokens": 12,
                "prompt_tokens_details": {"cached_tokens": 3},
            },
        )

    def test_cost_details_can_use_litellm_completion_cost(self):
        with patch("jee_tutor.agent.llm_client.completion_cost", return_value=0.25):
            self.assertEqual(VisionLLMClient._cost_details({}, "model"), {"total": 0.25})

    def test_cost_details_ignore_non_numeric_costs(self):
        with patch("jee_tutor.agent.llm_client.completion_cost", return_value="unknown"):
            self.assertEqual(VisionLLMClient._cost_details({}, "model"), {})

    def test_nested_token_detail_model_dump_is_compacted(self):
        self.assertEqual(
            VisionLLMClient._usage_details({"usage": {"prompt_tokens_details": TokenDetailModel()}}),
            {"prompt_tokens_details": {"cached_tokens": 3}},
        )


if __name__ == "__main__":
    unittest.main()
