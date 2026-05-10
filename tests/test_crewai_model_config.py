import unittest
from unittest.mock import Mock, patch

from agents.tutor_agent.config_loader import LLMConfig
from agents.tutor_agent.factories import (
    RateLimitedLLM,
    build_crewai_llm,
    build_diagnosis_task,
    build_tutor_agent,
)
from agents.tutor_agent.model_config import VisionModelConfig


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

        with patch("agents.tutor_agent.factories.LLM") as llm_class:
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

        with patch("agents.tutor_agent.factories.LLM") as llm_class:
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

    def test_build_agent_and_task_use_prompt_provider(self):
        prompt_provider = Mock()
        prompt_provider.get.side_effect = lambda key: Mock(text=f"text:{key}")
        vision_tool = object()
        llm = object()

        with (
            patch("agents.tutor_agent.factories.Agent") as agent_class,
            patch("agents.tutor_agent.factories.Task") as task_class,
        ):
            agent = build_tutor_agent(vision_tool, prompt_provider, llm)
            build_diagnosis_task(agent, prompt_provider)

        agent_class.assert_called_once()
        _, agent_kwargs = agent_class.call_args
        self.assertEqual(agent_kwargs["tools"], [vision_tool])
        self.assertIs(agent_kwargs["llm"], llm)
        self.assertFalse(agent_kwargs["allow_delegation"])
        task_class.assert_called_once()


if __name__ == "__main__":
    unittest.main()
