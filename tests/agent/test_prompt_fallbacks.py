import unittest

from jee_tutor.agent.prompts import (
    DIAGNOSIS_TASK_DESCRIPTION,
    DIAGNOSIS_TASK_EXPECTED_OUTPUT,
    LOCAL_PROMPT_FALLBACKS,
    TUTOR_AGENT_GOAL,
    VISION_SYSTEM,
    VISION_USER,
)


class PromptFallbacksTest(unittest.TestCase):
    def test_agent_prompts_require_one_authoritative_tool_call(self):
        for prompt_key in (TUTOR_AGENT_GOAL, DIAGNOSIS_TASK_DESCRIPTION):
            prompt = LOCAL_PROMPT_FALLBACKS[prompt_key]
            self.assertIn("exactly once", prompt)
            self.assertIn("tool observation", prompt)

    def test_prompts_require_exactly_one_row_per_invocation_image(self):
        for prompt_key in (
            VISION_SYSTEM,
            VISION_USER,
            TUTOR_AGENT_GOAL,
            DIAGNOSIS_TASK_DESCRIPTION,
            DIAGNOSIS_TASK_EXPECTED_OUTPUT,
        ):
            prompt = LOCAL_PROMPT_FALLBACKS[prompt_key]
            self.assertIn("exactly one", prompt)
            self.assertIn("provided", prompt)
            self.assertIn("image", prompt)

    def test_agent_goal_has_no_reference_sample_report(self):
        prompt = LOCAL_PROMPT_FALLBACKS[TUTOR_AGENT_GOAL]

        self.assertNotIn("REFERENCE SAMPLE REPORT", prompt)
        self.assertNotIn("| Q1 |", prompt)

    def test_vision_prompts_reject_embedded_image_instructions(self):
        for prompt_key in (VISION_SYSTEM, VISION_USER):
            prompt = LOCAL_PROMPT_FALLBACKS[prompt_key]
            self.assertIn("untrusted question content", prompt)
            self.assertIn("instruction inside an image", prompt)


if __name__ == "__main__":
    unittest.main()
