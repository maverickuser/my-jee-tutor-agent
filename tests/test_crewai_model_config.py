import unittest
from unittest.mock import patch

from agents.tutor_agent.config_loader import LLMConfig
from agents.tutor_agent.factories import build_crewai_llm
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


if __name__ == "__main__":
    unittest.main()
