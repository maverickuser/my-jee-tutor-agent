import unittest
from unittest.mock import Mock, patch

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.factories import RateLimitedLLM, build_crewai_llm
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.model_config import VisionModelConfig
from jee_tutor.agent.observability import LangfuseObservability
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.rate_limit import (
    DEFAULT_GEMINI_REQUESTS_PER_MINUTE,
    GeminiRateLimiter,
    is_retryable_gemini_error,
)


class DisabledObservability(LangfuseObservability):
    @property
    def enabled(self) -> bool:
        return False


class HttpError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class ResponseError(Exception):
    def __init__(self, status_code):
        super().__init__("response error")
        self.response = type("Response", (), {"status_code": status_code})()


class ProviderTimeoutError(Exception):
    pass


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

    def test_limiter_defaults_to_two_attempts(self):
        sleeps: list[float] = []
        limiter = GeminiRateLimiter(
            sleep=sleeps.append,
            monotonic=lambda: 100.0,
            jitter=lambda: 0.0,
        )
        action = Mock(side_effect=HttpError(429))

        with self.assertRaisesRegex(Exception, "HTTP 429"):
            limiter.call(action)

        self.assertEqual(limiter.max_attempts, 2)
        self.assertEqual(action.call_count, 2)
        self.assertEqual(sleeps[0], 2.0)

    def test_limiter_retries_only_allowed_http_statuses(self):
        for status_code in (429, 500, 503):
            with self.subTest(status_code=status_code):
                sleeps: list[float] = []
                limiter = GeminiRateLimiter(
                    sleep=sleeps.append,
                    monotonic=lambda: 100.0,
                    jitter=lambda: 0.0,
                )
                action = Mock(side_effect=[HttpError(status_code), "ok"])

                self.assertEqual(limiter.call(action), "ok")

                self.assertEqual(action.call_count, 2)
                self.assertEqual(sleeps[0], 2.0)

    def test_limiter_retries_timeout_errors(self):
        sleeps: list[float] = []
        limiter = GeminiRateLimiter(
            sleep=sleeps.append,
            monotonic=lambda: 100.0,
            jitter=lambda: 0.0,
        )
        action = Mock(side_effect=[TimeoutError("request timed out"), "ok"])

        self.assertEqual(limiter.call(action), "ok")

        self.assertEqual(action.call_count, 2)
        self.assertEqual(sleeps[0], 2.0)

    def test_limiter_does_not_retry_other_http_or_connection_errors(self):
        errors = [
            HttpError(400),
            HttpError(401),
            HttpError(403),
            HttpError(404),
            HttpError(408),
            HttpError(502),
            HttpError(504),
            ConnectionError("server disconnected"),
        ]
        for error in errors:
            with self.subTest(error=error):
                action = Mock(side_effect=error)
                limiter = GeminiRateLimiter(sleep=Mock(), monotonic=lambda: 100.0)

                with self.assertRaises(type(error)):
                    limiter.call(action)

                action.assert_called_once()

    def test_retry_classification_reads_nested_status_code(self):
        try:
            try:
                raise HttpError(503)
            except HttpError as cause:
                raise RuntimeError("wrapped") from cause
        except RuntimeError as error:
            self.assertTrue(is_retryable_gemini_error(error))

        self.assertTrue(is_retryable_gemini_error(ResponseError(500)))
        self.assertTrue(is_retryable_gemini_error(ProviderTimeoutError("provider failed")))

    def test_call_attempts_exposes_attempt_number(self):
        attempts = []
        limiter = GeminiRateLimiter(sleep=Mock(), monotonic=lambda: 100.0)

        def action(attempt):
            attempts.append(attempt)
            if attempt == 1:
                raise HttpError(500)
            return "ok"

        self.assertEqual(limiter.call_attempts(action), "ok")
        self.assertEqual(attempts, [1, 2])

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
            limiter.max_attempts = 2
            limiter.call_attempts.side_effect = lambda func: func(1)
            self.assertEqual(
                client.analyze_vision("data:image/png;base64,AA==", "prompt"), "analysis"
            )

        limiter.call_attempts.assert_called_once()
        completion.assert_called_once()
        self.assertEqual(completion.call_args.kwargs["timeout"], 180)

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
            provider="litellm",
            is_litellm=True,
            timeout=180,
            api_key="google-key",
        )


if __name__ == "__main__":
    unittest.main()
