import unittest

from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.tools import DEFAULT_VISION_USER_PROMPT, VisionAnalysisTool, VisionInput


class FakeVisionLLMClient(VisionLLMClient):
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def analyze_vision(self, image_data_uris, user_prompt):
        self.calls.append((image_data_uris, user_prompt))
        if self.error:
            raise self.error
        return "analysis"


class VisionToolTest(unittest.TestCase):
    def test_vision_input_defaults_missing_user_prompt(self):
        parsed = VisionInput.model_validate({})

        self.assertEqual(parsed.user_prompt, DEFAULT_VISION_USER_PROMPT)
        self.assertEqual(parsed.image_data_uris, [])

    def test_tool_run_defaults_missing_user_prompt(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(llm_client=llm_client)

        result = tool._run(["data:image/png;base64,ZmFrZQ=="])

        self.assertEqual(result, "analysis")
        self.assertEqual(
            llm_client.calls,
            [(["data:image/png;base64,ZmFrZQ=="], DEFAULT_VISION_USER_PROMPT)],
        )

    def test_tool_uses_preloaded_images_when_crewai_sends_placeholder_filename(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(
            llm_client=llm_client,
            preloaded_image_data_uris=["data:image/png;base64,cHJlbG9hZGVk"],
        )

        result = tool._run(["input_file_0.png"], "diagnose")

        self.assertEqual(result, "analysis")
        self.assertEqual(
            llm_client.calls,
            [(["data:image/png;base64,cHJlbG9hZGVk"], "diagnose")],
        )

    def test_tool_prefers_valid_tool_supplied_data_uris_over_preloaded_images(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(
            llm_client=llm_client,
            preloaded_image_data_uris=["data:image/png;base64,cHJlbG9hZGVk"],
        )

        tool._run(["data:image/png;base64,dG9vbA=="], "diagnose")

        self.assertEqual(
            llm_client.calls,
            [(["data:image/png;base64,dG9vbA=="], "diagnose")],
        )

    def test_tool_failure_includes_image_resolution_context(self):
        tool = VisionAnalysisTool(
            llm_client=FakeVisionLLMClient(error=ConnectionError("server disconnected")),
            preloaded_image_data_uris=["data:image/png;base64,cHJlbG9hZGVk"],
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Vision analyzer failed after resolving 1 image\\(s\\) "
            "from preloaded_invocation_images",
        ):
            tool._run(["input_file_0.png"], "diagnose")

    def test_tool_rejects_empty_image_input_with_clear_error(self):
        tool = VisionAnalysisTool(llm_client=FakeVisionLLMClient())

        with self.assertRaisesRegex(ValueError, "Vision analyzer received no images"):
            tool._run([], "diagnose")


if __name__ == "__main__":
    unittest.main()
