import unittest
import threading
import time
import json

from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.tools import (
    OutputValidationError,
    ToolExecutionStatus,
    VisionAnalysisTool,
    VisionInput,
    build_vision_tool,
)


class FakeVisionLLMClient(VisionLLMClient):
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def analyze_vision(self, image_data_uris, user_prompt=None, *, expected_question_numbers=None):
        self.calls.append((image_data_uris, user_prompt, expected_question_numbers))
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
            [(["data:image/png;base64,ZmFrZQ=="], None, None)],
        )

    def test_run_preloaded_uses_preloaded_images(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(
            llm_client=llm_client,
            preloaded_image_data_uris=["data:image/png;base64,cHJlbG9hZGVk"],
        )

        self.assertEqual(tool.run_preloaded(), "analysis")
        self.assertEqual(len(llm_client.calls), 1)

    def test_tool_replays_a_second_call_without_invoking_vision_again(self):
        llm_client = FakeVisionLLMClient()
        tool = VisionAnalysisTool(llm_client=llm_client)
        image = "data:image/png;base64,ZmFrZQ=="

        first = tool._run([image])
        second = tool._run([image])

        self.assertEqual(first, second)
        self.assertEqual(tool.call_state.call_count, 2)
        self.assertEqual(tool.call_state.successful_call_count, 1)
        self.assertEqual(tool.call_state.cached_replay_count, 1)
        self.assertEqual(llm_client.calls, [([image], None, None)])

    def test_tool_reexecutes_once_after_rejected_observation(self):
        class SequentialClient(FakeVisionLLMClient):
            def analyze_vision(self, image_data_uris, user_prompt=None, *, expected_question_numbers=None):
                self.calls.append((image_data_uris, user_prompt, expected_question_numbers))
                return f"analysis-{len(self.calls)}"

        client = SequentialClient()
        tool = VisionAnalysisTool(
            llm_client=client,
            preloaded_image_data_uris=["data:image/png;base64,x"],
        )

        self.assertEqual(tool.run_preloaded(), "analysis-1")
        tool.call_state.reject_observation("question_count_mismatch")
        self.assertEqual(tool.run_preloaded(), "analysis-2")

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(tool.call_state.execution_count, 2)
        self.assertEqual(tool.call_state.semantic_retry_count, 1)
        self.assertEqual(tool.call_state.observation_replaced_count, 1)
        self.assertFalse(tool.call_state.observation_rejected)

    def test_tool_does_not_replay_rejected_observation_when_retry_exhausted(self):
        tool = VisionAnalysisTool(
            llm_client=FakeVisionLLMClient(),
            preloaded_image_data_uris=["data:image/png;base64,x"],
        )

        self.assertEqual(tool.run_preloaded(), "analysis")
        tool.call_state.reject_observation("schema_invalid")
        tool.call_state.semantic_retry_count = tool.call_state.semantic_retry_budget

        with self.assertRaisesRegex(RuntimeError, "semantic retry budget exhausted"):
            tool.run_preloaded()

        self.assertEqual(tool.call_state.execution_count, 1)
        self.assertEqual(tool.call_state.semantic_retry_exhausted_count, 1)

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
            [(["data:image/png;base64,cHJlbG9hZGVk"], None, None)],
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
            [(["data:image/png;base64,cHJlbG9hZGVk"], None, None)],
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

    def test_duplicate_attempt_does_not_overwrite_original_provider_error(self):
        tool = VisionAnalysisTool(
            llm_client=FakeVisionLLMClient(error=TimeoutError("provider timed out")),
            preloaded_image_data_uris=["data:image/png;base64,cHJlbG9hZGVk"],
        )

        with self.assertRaises(RuntimeError):
            tool.run_preloaded()
        with self.assertRaisesRegex(RuntimeError, "Cached vision analyzer failure"):
            tool.run_preloaded()

        self.assertEqual(
            tool.call_state.first_error,
            "TimeoutError: provider timed out",
        )

    def test_tool_rejects_empty_image_input_with_clear_error(self):
        tool = VisionAnalysisTool(llm_client=FakeVisionLLMClient())

        with self.assertRaisesRegex(ValueError, "Vision analyzer received no images"):
            tool._run([])

    def test_expected_numbers_are_passed_and_non_data_input_is_supported(self):
        client = MockVisionClient()
        tool = VisionAnalysisTool(
            llm_client=client,
            expected_question_numbers=["6"],
        )
        tool._run(["input.png"])
        self.assertEqual(client.expected, ["6"])

    def test_tool_batches_images_in_groups_of_three_and_merges_json(self):
        class BatchAwareClient(FakeVisionLLMClient):
            def __init__(self):
                super().__init__()
                self.question_index = 0

            def analyze_vision(self, image_data_uris, user_prompt=None, *, expected_question_numbers=None):
                self.calls.append((image_data_uris, user_prompt, expected_question_numbers))
                questions = []
                for index, _image in enumerate(image_data_uris, start=1):
                    self.question_index += 1
                    number = str(self.question_index)
                    questions.append(
                        {
                            "question_number": number,
                            "chapter": "Electrostatics",
                            "topic": "Capacitance",
                            "what_you_thought": f"batch {len(self.calls)} image {index}",
                            "why_that_thought_is_wrong": "missed charge sharing",
                            "exact_concept_gap": "conservation of charge",
                            "what_you_must_deep_dive": "series and parallel capacitors",
                        }
                    )
                return json.dumps({"questions": questions})

        client = BatchAwareClient()
        tool = VisionAnalysisTool(
            llm_client=client,
            preloaded_image_data_uris=[
                "data:image/png;base64,1",
                "data:image/png;base64,2",
                "data:image/png;base64,3",
                "data:image/png;base64,4",
            ],
            expected_question_numbers=["1", "2", "3", "4"],
        )

        result = tool.run_preloaded()

        self.assertEqual(len(client.calls), 2)
        self.assertEqual([len(call[0]) for call in client.calls], [3, 1])
        self.assertEqual(json.loads(result)["questions"][0]["question_number"], "1")
        self.assertEqual(json.loads(result)["questions"][-1]["question_number"], "4")

    def test_merge_batch_outputs_covers_markdown_single_and_error_paths(self):
        tool = VisionAnalysisTool(llm_client=FakeVisionLLMClient())
        markdown = (
            "| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | Exact Concept Gap | What You Must Deep-Dive |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 1 | Electrostatics | Capacitors | x | y | z | a |\n"
        )
        merged = tool._merge_batch_outputs([markdown, markdown], [1, 1], 2)
        self.assertIn("| 1 | Electrostatics | Capacitors | x | y | z | a |", merged)

        self.assertEqual(tool._merge_batch_outputs(["analysis"], [1], 1), "analysis")

        with self.assertRaisesRegex(RuntimeError, "no batch outputs"):
            tool._merge_batch_outputs([], [], 0)

        with self.assertRaisesRegex(OutputValidationError, "Batched vision outputs"):
            tool._merge_batch_outputs(["{x}", "| row |"], [1, 1], 2)

    def test_markdown_table_helpers_handle_escaping_and_validation(self):
        tool = VisionAnalysisTool(llm_client=FakeVisionLLMClient())
        headers, rows = tool._parse_markdown_table(
            "| A | B |\n| --- | --- |\n| x\\\\y | p | q |\n"
        )
        self.assertEqual(headers, ["A", "B"])
        self.assertEqual(rows[0], ["x\\\\y", "p", "q"])
        self.assertTrue(tool._looks_like_markdown("| a |\n| --- |\n| b |\n"))
        self.assertFalse(tool._looks_like_json("analysis"))
        self.assertEqual(tool._split_markdown_row("| a \\| b | c |"), ["a \\| b", "c"])
        self.assertTrue(tool._is_separator_cells(["---", ":---:", "----"]))
        self.assertEqual(tool._escape_markdown_cell("x|\ny\\z"), "x\\| y\\\\z")

        with self.assertRaisesRegex(OutputValidationError, "markdown table"):
            tool._parse_markdown_table("| only one line |\n")

    def test_wait_for_or_replay_returns_observation_and_reconstructs_failure(self):
        tool = VisionAnalysisTool(llm_client=FakeVisionLLMClient())
        tool.call_state.status = ToolExecutionStatus.SUCCEEDED
        tool.call_state.observation = "cached observation"
        self.assertEqual(tool._wait_for_or_replay(), "cached observation")
        self.assertEqual(tool.call_state.cached_replay_count, 1)

        tool.call_state.status = ToolExecutionStatus.FAILED
        tool.call_state.error_snapshot = None
        with self.assertRaisesRegex(RuntimeError, "invalid memoization"):
            tool._wait_for_or_replay()

    def test_waiter_timeout_and_invalid_memoization_state(self):
        tool = VisionAnalysisTool(llm_client=FakeVisionLLMClient())
        tool.call_state.status = ToolExecutionStatus.RUNNING
        tool.call_state.waiter_timeout_seconds = 0
        with self.assertRaises(TimeoutError):
            tool.run_preloaded()

        tool.call_state.status = ToolExecutionStatus.FAILED
        with self.assertRaisesRegex(RuntimeError, "invalid memoization"):
            tool.run_preloaded()

    def test_concurrent_callers_share_one_execution(self):
        release = threading.Event()

        class BlockingClient(FakeVisionLLMClient):
            def analyze_vision(self, image_data_uris, user_prompt=None):
                self.calls.append((image_data_uris, user_prompt))
                release.wait(1)
                return "analysis"

        client = BlockingClient()
        tool = VisionAnalysisTool(
            llm_client=client,
            preloaded_image_data_uris=["data:image/png;base64,x"],
        )
        outputs = []
        threads = [threading.Thread(target=lambda: outputs.append(tool.run_preloaded())) for _ in range(3)]
        for thread in threads:
            thread.start()
        time.sleep(0.01)
        release.set()
        for thread in threads:
            thread.join(1)
        self.assertEqual(outputs, ["analysis"] * 3)
        self.assertEqual(tool.call_state.execution_count, 1)


class MockVisionClient(VisionLLMClient):
    def __init__(self):
        self.expected = None

    def analyze_vision(self, images, *, expected_question_numbers=None):
        self.expected = expected_question_numbers
        return "analysis"


if __name__ == "__main__":
    unittest.main()
