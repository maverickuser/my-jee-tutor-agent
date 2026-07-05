import tempfile
import unittest
from pathlib import Path

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.model_config import CrewAIModelConfig, ModelSettings, VisionModelConfig


class ConfigAndModelTest(unittest.TestCase):
    def test_load_missing_config_returns_empty_config(self):
        config = LLMConfig.load("missing-config.toml")

        self.assertEqual(config.values, {})
        self.assertEqual(config.get("missing", "key", "fallback"), "fallback")

    def test_loads_explicit_toml_and_returns_deepcopy_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "llm.toml"
            path.write_text("[completion]\ntemperature = 0.2\n", encoding="utf-8")

            config = LLMConfig.load(str(path))

        section = config.section("completion")
        section["temperature"] = 1.0

        self.assertEqual(config.get("completion", "temperature"), 0.2)

    def test_nested_section_returns_empty_for_scalar_intermediate(self):
        config = LLMConfig({"langfuse": "disabled"})

        self.assertEqual(config.section("langfuse.prompts"), {})

    def test_model_settings_excludes_empty_optional_kwargs(self):
        kwargs = ModelSettings(model="custom/model").to_litellm_kwargs()

        self.assertEqual(kwargs, {"model": "custom/model"})

    def test_openai_model_uses_openai_key_and_api_base(self):
        config = LLMConfig(
            {
                "vision": {"model": "openai/gpt-4o"},
                "litellm": {"api_base": "https://proxy.example.com"},
                "completion": {"timeout": 60},
            }
        )
        settings = VisionModelConfig(
            environ={"OPENAI_API_KEY": "openai-key"},
            config=config,
        ).resolve()

        self.assertEqual(
            settings.to_litellm_kwargs(),
            {
                "model": "openai/gpt-4o",
                "api_key": "openai-key",
                "api_base": "https://proxy.example.com",
                "timeout": 60,
            },
        )

    def test_unknown_model_uses_litellm_key(self):
        settings = VisionModelConfig(
            environ={"VISION_MODEL": "custom/provider-model", "LITELLM_API_KEY": "litellm-key"},
            config=LLMConfig({}),
        ).resolve()

        self.assertEqual(settings.api_key, "litellm-key")

    def test_missing_api_key_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, "No API key configured"):
            VisionModelConfig(
                environ={"VISION_MODEL": "openai/gpt-4o"},
                config=LLMConfig({}),
            ).resolve()

    def test_bedrock_model_uses_aws_default_region_fallback(self):
        settings = VisionModelConfig(
            environ={
                "VISION_MODEL": "amazon/nova-pro",
                "AWS_DEFAULT_REGION": "us-east-1",
            },
            config=LLMConfig({}),
        ).resolve()

        self.assertEqual(settings.aws_region_name, "us-east-1")

    def test_crewai_model_defaults_to_flash(self):
        settings = CrewAIModelConfig(
            environ={"GOOGLE_API_KEY": "google-key"},
            config=LLMConfig({}),
        ).resolve()

        self.assertEqual(settings.model, "gemini/gemini-3-flash-preview")


if __name__ == "__main__":
    unittest.main()
