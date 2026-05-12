import unittest
from unittest.mock import Mock, patch

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.factories import RateLimitedLLM, build_crewai_llm
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.model_config import VisionModelConfig
from jee_tutor.agent.observability import LangfuseObservability
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.rate_limit import DEFAULT_GEMINI_REQUESTS_PER_MINUTE, GeminiRateLimiter


class DisabledObservability(LangfuseObservability):
    @property
    def enabled(self) -> bool:
        return False


class GeminiRateLimitTest(unittest.TestCase):
    def test_limiter_spaces_calls_to_default_requests_per_minute(self):
        sleeps: list[float] = []
        now = 100.0
        limiter = GeminiRateLimiter(
            sleep=sleeps.append,
            monotonic=lambda: now,
        )
        action = Mock(return_value="ok")

        limiter.call(action)
        limiter.call(action)

        self.assertEqual(action.call_count, 2)
        self.assertEqual(DEFAULT_GEMINI_REQUESTS_PER_MINUTE, 100)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.6)

    def test_limiter_backs_off_and_retries_rate_limit_errors(self):
        sleeps: list[float] = []
        limiter = GeminiRateLimiter(
            sleep=sleeps.append,
            monotonic=lambda: 100.0,
            jitter=lambda: 0.0,
        )
        action = Mock(side_effect=[Exception("429 rate limit"), "ok"])

        self.assertEqual(limiter.call(action), "ok")

        self.assertEqual(action.call_count, 2)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(sleeps[0], 2.0)
        self.assertAlmostEqual(sleeps[1], 0.6)

    def test_limiter_backs_off_and_retries_transient_connection_errors(self):
        sleeps: list[float] = []
        limiter = GeminiRateLimiter(
            sleep=sleeps.append,
            monotonic=lambda: 100.0,
            jitter=lambda: 0.0,
        )
        action = Mock(
            side_effect=[
                Exception("APIConnectionError: Server disconnected without sending a response."),
                "ok",
            ]
        )

        self.assertEqual(limiter.call(action), "ok")

        self.assertEqual(action.call_count, 2)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(sleeps[0], 2.0)
        self.assertAlmostEqual(sleeps[1], 0.6)

    def test_vision_client_routes_gemini_completion_through_limiter(self):
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
        prompt_provider = PromptProvider(
            config=config,
            observability=DisabledObservability(config),
        )
        completion = Mock(
            return_value={"choices": [{"message": {"content": "analysis"}}]},
        )
        client = VisionLLMClient(
            model_config=model_config,
            observability=DisabledObservability(config),
            prompt_provider=prompt_provider,
            completion_fn=completion,
        )

        with patch("jee_tutor.agent.llm_client.gemini_rate_limiter") as limiter:
            limiter.call.side_effect = lambda func, **kwargs: func(**kwargs)
            self.assertEqual(
                client.analyze_vision("data:image/png;base64,AA==", "prompt"), "analysis"
            )

        limiter.call.assert_called_once()
        completion.assert_called_once()

    def test_crewai_gemini_llm_is_rate_limited(self):
        config = LLMConfig({"vision": {"model": "gemini/gemini-3-flash-preview"}})
        model_config = VisionModelConfig(
            environ={"GOOGLE_API_KEY": "google-key"},
            config=config,
        )

        with patch("jee_tutor.agent.factories.LLM") as llm_class:
            llm = build_crewai_llm(model_config)

        self.assertIsInstance(llm, RateLimitedLLM)
        llm_class.assert_called_once_with(
            model="gemini/gemini-3-flash-preview",
            api_key="google-key",
        )


if __name__ == "__main__":
    unittest.main()
