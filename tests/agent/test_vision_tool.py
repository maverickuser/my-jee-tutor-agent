import unittest

from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.tools import VisionAnalysisTool, VisionInput, build_vision_tool


class FakeVisionLLMClient(VisionLLMClient):
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def analyze_vision(self, image_data_uris, user_prompt=None):
        self.calls.append((image_data_uris, user_prompt))
        if self.error:
            raise self.error
        return "analysis"


class VisionToolTest(unittest.TestCase):
    def test_built_tool_returns_vision_output_as_final_agent_answer(self):
        tool = build_vision_tool(llm_client=FakeVisionLLMClient())

        self.assertTrue(tool.result_as_answer)

    def test_tool_description_instructs_empty_json_input_for_preloaded_images(self):
        tool = VisionAnalysisTool(llm_client=FakeVisionLLMClient())

        self.assertIn("for example {}", tool.description)
        self.assertIn("preloaded", tool.description)

    def test_vision_input_defaults_missing_user_prompt(self):
        parsed = VisionInput.model_validate({})

        self.assertEqual(parsed.image_data_uris, [])

    def test_vision_input_does_not_expose_user_prompt_override(self):
        schema = VisionInput.model_json_schema()

        self.assertNotIn("user_prompt", schema["properties"])

    def test_tool_run_defaults_missing_user_prompt(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(llm_client=llm_client)

        result = tool._run(["data:image/png;base64,ZmFrZQ=="])

        self.assertEqual(result, "analysis")
        self.assertEqual(
            llm_client.calls,
            [(["data:image/png;base64,ZmFrZQ=="], None)],
        )

    def test_tool_rejects_a_second_call_without_invoking_vision_again(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(llm_client=llm_client)
        image = "data:image/png;base64,ZmFrZQ=="

        tool._run([image])

        with self.assertRaisesRegex(RuntimeError, "exactly once"):
            tool._run([image])

        self.assertEqual(tool.call_state.call_count, 2)
        self.assertEqual(tool.call_state.successful_call_count, 1)
        self.assertEqual(llm_client.calls, [([image], None)])

    def test_tool_uses_preloaded_images_when_crewai_sends_placeholder_filename(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(
            llm_client=llm_client,
            preloaded_image_data_uris=["data:image/png;base64,cHJlbG9hZGVk"],
        )

        result = tool._run(["input_file_0.png"])

        self.assertEqual(result, "analysis")
        self.assertEqual(
            llm_client.calls,
            [(["data:image/png;base64,cHJlbG9hZGVk"], None)],
        )

    def test_tool_uses_preloaded_images_over_tool_supplied_data_uris(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(
            llm_client=llm_client,
            preloaded_image_data_uris=["data:image/png;base64,cHJlbG9hZGVk"],
        )

        tool._run(["data:image/png;base64,dG9vbA=="])

        self.assertEqual(
            llm_client.calls,
            [(["data:image/png;base64,cHJlbG9hZGVk"], None)],
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
            tool._run(["input_file_0.png"])

    def test_tool_rejects_empty_image_input_with_clear_error(self):
        tool = VisionAnalysisTool(llm_client=FakeVisionLLMClient())

        with self.assertRaisesRegex(ValueError, "Vision analyzer received no images"):
            tool._run([])


if __name__ == "__main__":
    unittest.main()
