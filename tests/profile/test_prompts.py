import json
import unittest

from jee_tutor.profile.prompts import (
    profile_report_system_prompt,
    profile_report_user_prompt,
)
from jee_tutor.profile.semantic import (
    SemanticGapCluster,
    build_longitudinal_evidence_pack,
)
from tests.profile.test_semantic_evidence_pack import evidence


class ProfilePromptsTest(unittest.TestCase):
    def test_student_profile_agent_prompt_module_reexports_profile_prompts(self):
        from agents.student_profile.prompts import profile_report_system_prompt as task_prompt

        self.assertEqual(task_prompt(), profile_report_system_prompt())

    def test_profile_report_system_prompt_requires_evidence_and_actionability(self):
        prompt = profile_report_system_prompt()

        self.assertIn("Strict Operational Rules", prompt)
        self.assertIn("Zero Hallucination", prompt)
        self.assertIn("Evidence Processing", prompt)
        self.assertIn("evidence_reference", prompt)
        self.assertIn("Recurring gap", prompt)
        self.assertIn("exact_concept_gap", prompt)
        self.assertIn("deep_dive_recommendation", prompt)
        self.assertIn("likely_thought", prompt)
        self.assertIn("why_wrong", prompt)

    def test_profile_report_user_prompt_contains_validated_evidence_pack(self):
        item = evidence("r1:q1", "r1")
        pack = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=[item],
            clusters=[
                SemanticGapCluster(
                    cluster_id="isolated",
                    cluster_type="same_underlying_gap",
                    title="Projectile components",
                    evidence_ids=["r1:q1"],
                    rationale="single report",
                )
            ],
        )

        prompt = profile_report_user_prompt(pack)
        self.assertIn("<evidence_pack>", prompt)
        self.assertIn("</evidence_pack>", prompt)
        evidence_json = prompt.split("<evidence_pack>\n", 1)[1].split("\n</evidence_pack>", 1)[0]
        payload = json.loads(evidence_json)

        self.assertEqual(payload["subject"], "Physics")
        self.assertEqual(
            payload["evidence_index"]["r1:q1"]["evidence_reference"],
            "2026-07-18 : TEST_r1 : Q1",
        )


if __name__ == "__main__":
    unittest.main()
