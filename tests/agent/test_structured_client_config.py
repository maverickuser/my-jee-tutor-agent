import json
import unittest
from unittest.mock import Mock

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.model_config import FinalEvaluatorModelConfig, VisionModelConfig
from tests.agent.test_diagnosis_output import question


class DisabledObservability:
    @property
    def enabled(self):
        return False

    def generation_span(self, **kwargs):
        from contextlib import nullcontext

        return nullcontext()


class StaticPrompts:
    def get(self, key):
        return Mock(text="prompt", langfuse_prompt=None)


class StructuredClientConfigTest(unittest.TestCase):
    def test_gemini_structured_request_parses_and_canonicalizes(self):
        config = LLMConfig(
            {
                "vision": {"model": "gemini/gemini-2.5-pro"},
                "structured_diagnosis": {
                    "enabled": True,
                    "allow_legacy_markdown": False,
                },
            }
        )
        completion = Mock(
            return_value={
                "choices": [{"message": {"content": json.dumps({"questions": [question()]})}}]
            }
        )
        client = VisionLLMClient(
            model_config=VisionModelConfig(
                environ={"GOOGLE_API_KEY": "key"},
                config=config,
            ),
            observability=DisabledObservability(),
            prompt_provider=StaticPrompts(),
            completion_fn=completion,
        )

        output = client.analyze_vision(
            ["data:image/png;base64,x"],
            expected_question_numbers=["6"],
        )

        self.assertEqual(json.loads(output)["questions"][0]["question_number"], "6")
        kwargs = completion.call_args.kwargs
        self.assertEqual(kwargs["response_format"]["type"], "json_schema")
        self.assertFalse(kwargs["caching"])
        self.assertEqual(kwargs["num_retries"], 0)

    def test_unsupported_provider_fails_when_legacy_disabled(self):
        client = VisionLLMClient(
            model_config=VisionModelConfig(
                environ={"OPENAI_API_KEY": "key"},
                config=LLMConfig(
                    {
                        "vision": {"model": "openai/gpt-4o"},
                        "structured_diagnosis": {
                            "enabled": True,
                            "allow_legacy_markdown": False,
                        },
                    }
                ),
            ),
            observability=DisabledObservability(),
            prompt_provider=StaticPrompts(),
        )
        with self.assertRaisesRegex(ValueError, "verified Gemini"):
            client.analyze_vision(["data:image/png;base64,x"])

    def test_final_evaluator_model_is_pinned_and_resolves_auth(self):
        settings = FinalEvaluatorModelConfig(
            environ={"GOOGLE_API_KEY": "key"},
            config=LLMConfig({}),
        ).resolve()
        self.assertEqual(settings.model, "gemini/gemini-2.5-flash")
        self.assertEqual(settings.completion_options["temperature"], 0)
        self.assertEqual(settings.completion_options["timeout"], 180)

        with self.assertRaisesRegex(ValueError, "must be pinned"):
            FinalEvaluatorModelConfig(
                environ={"GOOGLE_API_KEY": "key"},
                config=LLMConfig({"final_evaluator": {"model": "gemini/other"}}),
            ).resolve()
