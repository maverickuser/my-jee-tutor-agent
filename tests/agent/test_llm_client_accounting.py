import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.llm_client import (
    VisionLLMClient,
    _compact_token_detail,
    _estimate_image_bytes_from_data_uri,
    _response_value,
)
from jee_tutor.agent.model_config import VisionModelConfig
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.prompts import VISION_SYSTEM, VISION_USER


class RecordingGeneration:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class RecordingObservability:
    def __init__(self):
        self.generation = RecordingGeneration()
        self.prompt_names = []
        self.generation_spans = []

    @contextmanager
    def generation_span(self, **kwargs):
        self.generation_spans.append(kwargs)
        yield self.generation

    def get_text_prompt(self, name, fallback):
        self.prompt_names.append(name)
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
    def test_analyze_vision_resolves_system_and_user_prompts(self):
        config = LLMConfig(
            {
                "vision": {"model": "gemini/gemini-3-flash-preview"},
                "completion": {"temperature": 0.2},
                "langfuse": {
                    "prompts": {
                        VISION_SYSTEM: "system-prompt-name",
                        VISION_USER: "user-prompt-name",
                    }
                },
            }
        )
        observability = RecordingObservability()
        prompt_provider = PromptProvider(config=config, observability=observability)
        model_config = VisionModelConfig(
            environ={"GOOGLE_API_KEY": "google-key"},
            config=config,
        )
        completion = Mock(return_value={"choices": [{"message": {"content": "analysis"}}]})
        client = VisionLLMClient(
            model_config=model_config,
            observability=observability,
            prompt_provider=prompt_provider,
            completion_fn=completion,
        )

        with patch("jee_tutor.agent.llm_client.gemini_rate_limiter") as limiter:
            limiter.max_attempts = 2
            limiter.call_attempts.side_effect = lambda func: func(1)

            self.assertEqual(client.analyze_vision("data:image/png;base64,AA=="), "analysis")

        self.assertEqual(observability.prompt_names, ["system-prompt-name", "user-prompt-name"])
        messages = completion.call_args.kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Question Number", messages[1]["content"][0]["text"])

    def test_request_size_summary_counts_prompt_and_image_payload(self):
        request_kwargs = {
            "messages": [
                {"role": "system", "content": "system text"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "user prompt"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,ZmFrZQ=="},
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64,c2Vjb25k"},
                        },
                    ],
                },
            ]
        }

        self.assertEqual(
            VisionLLMClient._request_size_summary(request_kwargs),
            {
                "message_count": 2,
                "system_chars": 11,
                "user_text_chars": 11,
                "image_count": 2,
                "image_uri_chars": 61,
                "image_bytes_estimate": 10,
            },
        )

    def test_analyze_vision_forces_stateless_completion_kwargs(self):
        config = LLMConfig(
            {
                "vision": {"model": "gemini/gemini-3-flash-preview"},
                "completion": {
                    "temperature": 0.2,
                    "caching": True,
                    "cache": {"ttl": 300},
                    "cached_content": "cachedContents/stale",
                    "cachedContent": "cachedContents/staleCamel",
                    "preset_cache_key": "stale-cache-key",
                    "extra_body": {
                        "cached_content": "cachedContents/stale-extra",
                        "cachedContent": "cachedContents/stale-extra-camel",
                        "safe": "kept",
                    },
                },
            }
        )
        observability = RecordingObservability()
        prompt_provider = PromptProvider(config=config, observability=observability)
        model_config = VisionModelConfig(
            environ={"GOOGLE_API_KEY": "google-key"},
            config=config,
        )
        completion = Mock(return_value={"choices": [{"message": {"content": "analysis"}}]})
        client = VisionLLMClient(
            model_config=model_config,
            observability=observability,
            prompt_provider=prompt_provider,
            completion_fn=completion,
        )

        with patch("jee_tutor.agent.llm_client.gemini_rate_limiter") as limiter:
            limiter.max_attempts = 2
            limiter.call_attempts.side_effect = lambda func: func(1)

            self.assertEqual(client.analyze_vision("data:image/png;base64,AA=="), "analysis")

        kwargs = completion.call_args.kwargs
        self.assertFalse(kwargs["caching"])
        self.assertEqual(kwargs["cache"], {"no-cache": True})
        self.assertEqual(kwargs["num_retries"], 0)
        self.assertNotIn("cached_content", kwargs)
        self.assertNotIn("cachedContent", kwargs)
        self.assertNotIn("preset_cache_key", kwargs)
        self.assertEqual(kwargs["extra_body"], {"safe": "kept"})

    def test_structured_output_rejects_non_gemini_without_legacy_mode(self):
        config = LLMConfig(
            {
                "vision": {"model": "openai/gpt-4o"},
                "completion": {"temperature": 0.2},
                "structured_diagnosis": {
                    "enabled": True,
                    "allow_legacy_markdown": False,
                },
            }
        )
        observability = RecordingObservability()
        client = VisionLLMClient(
            model_config=VisionModelConfig(environ={"OPENAI_API_KEY": "openai-key"}, config=config),
            observability=observability,
            prompt_provider=PromptProvider(config=config, observability=observability),
            completion_fn=Mock(),
        )

        with self.assertRaisesRegex(ValueError, "Structured diagnosis output is enabled only"):
            client.analyze_vision("data:image/png;base64,AA==")

    def test_structured_output_falls_back_to_markdown_when_legacy_mode_is_enabled(self):
        config = LLMConfig(
            {
                "vision": {"model": "openai/gpt-4o"},
                "completion": {"temperature": 0.2},
                "structured_diagnosis": {
                    "enabled": True,
                    "allow_legacy_markdown": True,
                },
            }
        )
        observability = RecordingObservability()
        prompt_provider = PromptProvider(config=config, observability=observability)
        client = VisionLLMClient(
            model_config=VisionModelConfig(environ={"OPENAI_API_KEY": "openai-key"}, config=config),
            observability=observability,
            prompt_provider=prompt_provider,
            completion_fn=Mock(
                return_value={"choices": [{"message": {"content": " markdown "}}]}
            ),
        )

        self.assertEqual(client.analyze_vision("data:image/png;base64,AA=="), "markdown")

    def test_structured_output_rejects_unpinned_gemini_model(self):
        config = LLMConfig(
            {
                "vision": {"model": "gemini/gemini-3-flash-preview"},
                "completion": {"temperature": 0.2},
                "structured_diagnosis": {"enabled": True},
            }
        )
        observability = RecordingObservability()
        client = VisionLLMClient(
            model_config=VisionModelConfig(environ={"GOOGLE_API_KEY": "google-key"}, config=config),
            observability=observability,
            prompt_provider=PromptProvider(config=config, observability=observability),
            completion_fn=Mock(),
        )

        with self.assertRaisesRegex(ValueError, "Structured diagnosis model must be pinned"):
            client.analyze_vision("data:image/png;base64,AA==")

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
            limiter.max_attempts = 2
            limiter.call_attempts.side_effect = lambda func: func(1)

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
                        "input": 100,
                        "output": 25,
                        "total": 125,
                    },
                    "cost_details": {"total": 0.00042},
                }
            ],
        )
        self.assertEqual(
            observability.generation_spans[0]["metadata"],
            {"attempt": 1, "max_attempts": 2, "timeout_seconds": 180},
        )

    def test_each_retry_gets_a_separate_generation_span(self):
        config = LLMConfig(
            {
                "vision": {"model": "gemini/gemini-3-flash-preview"},
                "completion": {"timeout": 60},
            }
        )
        observability = RecordingObservability()
        client = VisionLLMClient(
            model_config=VisionModelConfig(
                environ={"GOOGLE_API_KEY": "google-key"},
                config=config,
            ),
            observability=observability,
            prompt_provider=PromptProvider(config=config, observability=observability),
            completion_fn=Mock(
                side_effect=[
                    TimeoutError("timed out"),
                    {"choices": [{"message": {"content": "analysis"}}]},
                ]
            ),
        )

        with patch("jee_tutor.agent.llm_client.gemini_rate_limiter") as limiter:
            limiter.max_attempts = 2

            def run_attempts(func):
                with self.assertRaises(TimeoutError):
                    func(1)
                return func(2)

            limiter.call_attempts.side_effect = run_attempts
            self.assertEqual(client.analyze_vision("data:image/png;base64,AA=="), "analysis")

        self.assertEqual(
            [span["metadata"]["attempt"] for span in observability.generation_spans],
            [1, 2],
        )
        self.assertEqual(
            observability.generation.updates[0]["output"]["error_type"],
            "TimeoutError",
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
                    "input": 100,
                    "output": 25,
                    "total": 125,
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
        limiter.call_attempts.assert_not_called()

    def test_accounting_is_empty_without_usage_or_cost(self):
        with patch("jee_tutor.agent.llm_client.completion_cost", return_value=None):
            self.assertEqual(VisionLLMClient._generation_accounting({}, "model"), {})

    def test_request_size_summary_handles_non_list_messages(self):
        self.assertEqual(VisionLLMClient._request_size_summary({"messages": None}), {})

    def test_request_size_summary_ignores_malformed_message_parts(self):
        request_kwargs = {
            "messages": [
                "ignored",
                {"role": "assistant", "content": "ignored"},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": None}},
                        {"type": "image_url", "image_url": {}},
                        {"type": "image_url", "image_url": {"url": "http://example.com"}},
                        {"type": "unsupported", "text": "ignored"},
                    ],
                },
            ]
        }

        self.assertEqual(
            VisionLLMClient._request_size_summary(request_kwargs),
            {
                "message_count": 3,
                "system_chars": 0,
                "user_text_chars": 0,
                "image_count": 1,
                "image_uri_chars": 18,
                "image_bytes_estimate": 0,
            },
        )

    def test_response_value_and_image_estimation_helpers_handle_invalid_inputs(self):
        self.assertIsNone(_response_value({}, "usage"))
        self.assertEqual(_compact_token_detail("value"), "value")
        self.assertEqual(_estimate_image_bytes_from_data_uri("not-a-data-uri"), 0)
        self.assertEqual(
            _estimate_image_bytes_from_data_uri("data:image/png;base64,%%%"),
            0,
        )

    def test_usage_details_compact_pydantic_like_models(self):
        response = {"usage": UsageModel()}

        self.assertEqual(
            VisionLLMClient._usage_details(response),
            {
                "input": 10,
                "total": 12,
            },
        )

    def test_usage_details_compact_plain_objects_and_nested_details(self):
        response = type("Response", (), {"usage": UsageObject()})()

        self.assertEqual(
            VisionLLMClient._usage_details(response),
            {
                "prompt_tokens_details": {"cached_tokens": 3},
                "input": 10,
                "total": 12,
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

    def test_usage_details_preserve_native_langfuse_fields_and_gemini_extras(self):
        response = {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "input": 12,
                "output_reasoning_tokens": 2,
            }
        }

        self.assertEqual(
            VisionLLMClient._usage_details(response),
            {
                "input": 12,
                "output_reasoning_tokens": 2,
                "output": 5,
                "total": 15,
            },
        )


if __name__ == "__main__":
    unittest.main()
