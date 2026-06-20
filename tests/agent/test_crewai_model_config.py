import unittest
from unittest.mock import Mock, patch

from crewai.utilities.llm_utils import create_llm

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.factories import (
    RateLimitedLLM,
    _format_llm_failure,
    build_crewai_llm,
    build_diagnosis_task,
    build_tutor_agent,
)
from jee_tutor.agent.model_config import VisionModelConfig


class DummyGeminiLLM:
    def __init__(self, error: Exception | None = None):
        self.model = "gemini/gemini-3-flash-preview"
        self.temperature = 0.2
        self.stop = []
        self.error = error
        self.calls = []

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return "analysis"

    def supports_stop_words(self):
        return True

    def supports_function_calling(self):
        return False

    def get_context_window_size(self):
        return 4096


class FakeGeminiError(Exception):
    status_code = 400
    litellm_debug_info = "provider=gemini"


class NoProviderError(Exception):
    pass


class CrewAIModelConfigTest(unittest.TestCase):
    def test_crewai_llm_uses_gemini_google_api_key(self):
        config = LLMConfig(
            {
                "vision": {"model": "gemini/gemini-3-flash-preview"},
                "completion": {"temperature": 0.2},
            }
        )
        model_config = VisionModelConfig(
            environ={"GOOGLE_API_KEY": "google-key"},
            config=config,
        )

        with patch("jee_tutor.agent.factories.LLM") as llm_class:
            build_crewai_llm(model_config)

        llm_class.assert_called_once_with(
            model="gemini/gemini-3-flash-preview",
            api_key="google-key",
            temperature=0.2,
        )

    def test_crewai_llm_uses_aws_region_for_bedrock_model(self):
        config = LLMConfig(
            {
                "vision": {"model": "bedrock/anthropic.claude-3-5-sonnet"},
                "completion": {"temperature": 0.2},
            }
        )
        model_config = VisionModelConfig(
            environ={"AWS_REGION": "ap-south-1"},
            config=config,
        )

        with patch("jee_tutor.agent.factories.LLM") as llm_class:
            build_crewai_llm(model_config)

        llm_class.assert_called_once_with(
            model="bedrock/anthropic.claude-3-5-sonnet",
            aws_region_name="ap-south-1",
            temperature=0.2,
        )

    def test_rate_limited_llm_delegates_attributes(self):
        wrapped = Mock()
        wrapped.name = "wrapped"

        self.assertEqual(RateLimitedLLM(wrapped).name, "wrapped")

    def test_rate_limited_llm_is_preserved_by_crewai_create_llm(self):
        wrapped = RateLimitedLLM(DummyGeminiLLM())

        self.assertIs(create_llm(wrapped), wrapped)

    def test_rate_limited_llm_wraps_failures_with_context(self):
        wrapped = RateLimitedLLM(DummyGeminiLLM(error=FakeGeminiError("model unavailable")))

        with patch("jee_tutor.agent.factories.gemini_rate_limiter") as limiter:
            limiter.call.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)

            with self.assertRaises(RuntimeError) as exc_info:
                wrapped.call([{"role": "user", "content": "hello"}])

        message = str(exc_info.exception)
        self.assertIn(
            "CrewAI agent LLM call failed for model=gemini/gemini-3-flash-preview",
            message,
        )
        self.assertIn("provider=gemini", message)
        self.assertIn("status_code=400", message)
        self.assertIn("FakeGeminiError: model unavailable", message)
        self.assertIn("supports_function_calling=False", message)

    def test_rate_limited_llm_forwards_successful_call_through_rate_limiter(self):
        dummy = DummyGeminiLLM()
        wrapped = RateLimitedLLM(dummy)
        tool_function = object()

        with patch("jee_tutor.agent.factories.gemini_rate_limiter") as limiter:
            limiter.call.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)

            result = wrapped.call(
                [{"role": "user", "content": "hello"}],
                tools=[{"name": "tool"}],
                callbacks=["callback"],
                available_functions={"tool": tool_function},
            )

        self.assertEqual(result, "analysis")
        self.assertEqual(
            dummy.calls,
            [
                (
                    ([{"role": "user", "content": "hello"}],),
                    {
                        "tools": [{"name": "tool"}],
                        "callbacks": ["callback"],
                        "available_functions": {"tool": tool_function},
                    },
                )
            ],
        )

    def test_rate_limited_llm_delegates_capability_methods(self):
        wrapped = RateLimitedLLM(DummyGeminiLLM())

        self.assertTrue(wrapped.supports_stop_words())
        self.assertFalse(wrapped.supports_function_calling())
        self.assertEqual(wrapped.get_context_window_size(), 4096)

    def test_rate_limited_llm_handles_missing_or_failing_capability_methods(self):
        llm = Mock()
        llm.model_name = "gemini/gemini-3-flash-preview"
        llm.temperature = True
        llm.stop = "END"
        llm.supports_stop_words.side_effect = RuntimeError("stop failed")
        llm.supports_function_calling.side_effect = RuntimeError("functions failed")
        llm.get_context_window_size.side_effect = RuntimeError("window failed")

        wrapped = RateLimitedLLM(llm)

        self.assertEqual(wrapped.model, "gemini/gemini-3-flash-preview")
        self.assertIsNone(wrapped.temperature)
        self.assertEqual(wrapped.stop, ["END"])
        self.assertEqual(
            wrapped.supports_stop_words(),
            super(RateLimitedLLM, wrapped).supports_stop_words(),
        )
        self.assertFalse(wrapped.supports_function_calling())
        self.assertEqual(
            wrapped.get_context_window_size(),
            super(RateLimitedLLM, wrapped).get_context_window_size(),
        )

    def test_rate_limited_llm_uses_string_fallback_and_sequence_stop(self):
        llm = Mock()
        llm.model = " "
        llm.model_name = None
        llm.deployment_name = None
        llm.name = None
        llm.temperature = "hot"
        llm.stop = ["A", None, 3]
        llm.__str__ = Mock(return_value="fallback-model")

        wrapped = RateLimitedLLM(llm)

        self.assertEqual(wrapped.model, "fallback-model")
        self.assertIsNone(wrapped.temperature)
        self.assertEqual(wrapped.stop, ["A", "3"])

    def test_format_llm_failure_handles_plain_model_and_cause(self):
        cause = ValueError()
        error = NoProviderError()
        error.__cause__ = cause

        message = _format_llm_failure(
            operation="LLM call",
            model="local-model",
            exc=error,
        )

        self.assertIn("LLM call failed for model=local-model", message)
        self.assertIn("NoProviderError: [no message]", message)
        self.assertIn("cause=ValueError: [no message]", message)
        self.assertNotIn("provider=", message)

    def test_non_gemini_failure_has_no_function_calling_note(self):
        llm = DummyGeminiLLM(error=NoProviderError("offline"))
        llm.model = "openai/gpt-4o"
        wrapped = RateLimitedLLM(llm)

        with patch("jee_tutor.agent.factories.gemini_rate_limiter") as limiter:
            limiter.call.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)

            with self.assertRaises(RuntimeError) as exc_info:
                wrapped.call([{"role": "user", "content": "hello"}])

        self.assertNotIn("supports_function_calling=False", str(exc_info.exception))

    def test_build_agent_and_task_use_prompt_provider(self):
        prompt_provider = Mock()
        prompt_provider.get.side_effect = lambda key: Mock(text=f"text:{key}")
        vision_tool = object()
        llm = object()

        with (
            patch("jee_tutor.agent.factories.Agent") as agent_class,
            patch("jee_tutor.agent.factories.Task") as task_class,
        ):
            agent = build_tutor_agent(vision_tool, prompt_provider, llm)
            build_diagnosis_task(agent, prompt_provider)

        agent_class.assert_called_once()
        _, agent_kwargs = agent_class.call_args
        self.assertEqual(agent_kwargs["tools"], [vision_tool])
        self.assertIs(agent_kwargs["llm"], llm)
        self.assertFalse(agent_kwargs["allow_delegation"])
        task_class.assert_called_once()

    def test_build_agent_can_include_concept_graph_tool(self):
        prompt_provider = Mock()
        prompt_provider.get.side_effect = lambda key: Mock(text=f"text:{key}")
        vision_tool = object()
        graph_tool = object()

        with patch("jee_tutor.agent.factories.Agent") as agent_class:
            build_tutor_agent(vision_tool, prompt_provider, object(), extra_tools=[graph_tool])

        _, agent_kwargs = agent_class.call_args
        self.assertEqual(agent_kwargs["tools"], [vision_tool, graph_tool])


if __name__ == "__main__":
    unittest.main()
