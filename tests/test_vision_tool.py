import unittest

from agents.tutor_agent.llm_client import VisionLLMClient
from agents.tutor_agent.tools import DEFAULT_VISION_USER_PROMPT, VisionAnalysisTool, VisionInput


class FakeVisionLLMClient(VisionLLMClient):
    def __init__(self):
        self.calls = []

    def analyze_vision(self, image_data_uris, user_prompt):
        self.calls.append((image_data_uris, user_prompt))
        return "analysis"


class VisionToolTest(unittest.TestCase):
    def test_vision_input_defaults_missing_user_prompt(self):
        parsed = VisionInput.model_validate({"image_data_uris": ["data:image/png;base64,ZmFrZQ=="]})

        self.assertEqual(parsed.user_prompt, DEFAULT_VISION_USER_PROMPT)

    def test_tool_run_defaults_missing_user_prompt(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(llm_client=llm_client)

        result = tool._run(["data:image/png;base64,ZmFrZQ=="])

        self.assertEqual(result, "analysis")
        self.assertEqual(
            llm_client.calls,
            [(["data:image/png;base64,ZmFrZQ=="], DEFAULT_VISION_USER_PROMPT)],
        )


if __name__ == "__main__":
    unittest.main()
