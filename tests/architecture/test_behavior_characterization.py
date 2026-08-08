import hashlib
import unittest

from jee_tutor.agent.diagnosis_output import DiagnosisResponse, QuestionDiagnosis
from jee_tutor.agent.prompts import LOCAL_PROMPT_FALLBACKS
from jee_tutor.agent.rate_limit import GeminiRateLimiter
from jee_tutor.agent.tools import VisionAnalysisTool, VisionToolCallState
from jee_tutor.invocation.models import TutorInvocationPayload, TutorInvocationResponse
from jee_tutor.profile.hierarchical import _strand_system_prompt


EXPECTED_PROMPT_HASHES = {
    "vision_system": "acac753f30bb00829715a58cee8bb0cd947b4a6ff6c5d1c3888986a591455e9c",
    "vision_user": "ade945125763a16402df921c37143dda6da03c41dea38a52e477223a1ab100a9",
    "tutor_agent_goal": "0b93ed0e8716a8bcfa61b928fcf659f9f88199f1ac64dbeeec9be5497fbd2ff6",
    "tutor_agent_backstory": "2d6781d67cad6ca9eccfa2ac35de88ccf725cfe823529fa68d0f510cd9b44241",
    "diagnosis_task_description": "3704825d0695b18377d2ad6674c6b900510c8ee8365c851175135ef65b59478f",
    "diagnosis_task_expected_output": "c524aa8bd8addd783c246f056952a71e6119bbf5dd080c1ef14959d563e257d3",
}


class BehaviorCharacterizationTest(unittest.TestCase):
    def test_prompt_text_is_unchanged_by_model_routing(self):
        actual = {
            name: hashlib.sha256(text.encode()).hexdigest()
            for name, text in LOCAL_PROMPT_FALLBACKS.items()
        }
        self.assertEqual(actual, EXPECTED_PROMPT_HASHES)
        self.assertEqual(
            hashlib.sha256(_strand_system_prompt().encode()).hexdigest(),
            "9ce93063b401fb9ac33b28301bdbeaa8eefb17f6c338792b9af394216a48f278",
        )

    def test_tool_batching_and_retry_contracts_are_unchanged(self):
        self.assertEqual(VisionAnalysisTool.model_fields["name"].default, "jee_question_vision_analyzer")
        self.assertEqual(VisionAnalysisTool.model_fields["max_images_per_call"].default, 3)
        self.assertEqual(VisionToolCallState().semantic_retry_budget, 1)
        self.assertEqual(GeminiRateLimiter().max_attempts, 2)

    def test_public_payload_response_and_diagnosis_fields_are_unchanged(self):
        self.assertEqual(
            set(TutorInvocationPayload.model_fields),
            {
                "task",
                "subject",
                "image_s3_prefix",
                "image_data_uri",
                "recipient_email",
                "save_analysis_pdf",
                "idempotency_key",
            },
        )
        self.assertNotIn("execution_profile", TutorInvocationPayload.model_fields)
        self.assertNotIn("model", TutorInvocationPayload.model_fields)
        self.assertIn("analysis", TutorInvocationResponse.model_fields)
        self.assertEqual(
            set(DiagnosisResponse.model_fields),
            {"questions"},
        )
        self.assertEqual(
            set(QuestionDiagnosis.model_fields),
            {
                "question_number",
                "chapter",
                "topic",
                "what_you_thought",
                "why_that_thought_is_wrong",
                "exact_concept_gap",
                "what_you_must_deep_dive",
            },
        )


if __name__ == "__main__":
    unittest.main()
