import unittest

from jee_tutor.profile.semantic import (
    SemanticGapCluster,
    build_longitudinal_evidence_pack,
)
from jee_tutor.profile.reporting import (
    LiteLLMProfileReportWriter,
    ProfileAnalysisService,
    validate_profile_report,
)
from tests.profile.test_semantic_evidence_pack import evidence


class ProfileReportingTest(unittest.TestCase):
    def test_profile_report_sections_prioritize_recurring_and_include_teacher_notes(self):
        items = [
            evidence("r1:q1", "r1"),
            evidence("r2:q1", "r2"),
            evidence("r3:q1", "r3", gap="Circular motion"),
        ]
        pack = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=items,
            clusters=[
                SemanticGapCluster(
                    cluster_id="recurring",
                    cluster_type="same_underlying_gap",
                    title="Projectile components",
                    evidence_ids=["r1:q1", "r2:q1"],
                    rationale="same gap",
                ),
                SemanticGapCluster(
                    cluster_id="isolated",
                    cluster_type="same_underlying_gap",
                    title="Circular motion",
                    evidence_ids=["r3:q1"],
                    rationale="single report",
                ),
            ],
        )

        report = ProfileAnalysisService().generate(pack)
        markdown = ProfileAnalysisService.render_markdown(report)

        validate_profile_report(report, pack)
        self.assertIn("Projectile components", report.recurring_gaps[0])
        self.assertIn("Reteach and drill", report.teacher_intervention_notes[0])
        self.assertIn("## Study Priorities", markdown)
        self.assertIn("r1:q1", "\n".join(report.evidence_appendix))

    def test_one_report_profile_uses_early_indicator_language_without_recurring_claim(self):
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

        report = ProfileAnalysisService().generate(pack)

        validate_profile_report(report, pack)
        self.assertEqual(report.recurring_gaps, [])
        self.assertIn("early indicator", report.isolated_gaps[0])
        self.assertIn("Monitor before calling this recurring", report.teacher_intervention_notes[0])

    def test_profile_report_validation_rejects_missing_evidence_reference(self):
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
        report = ProfileAnalysisService().generate(pack)
        report.evidence_appendix = []

        with self.assertRaisesRegex(ValueError, "evidence appendix"):
            validate_profile_report(report, pack)

    def test_profile_report_can_be_written_by_llm_client(self):
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

        def completion_fn(**kwargs):
            self.assertEqual(kwargs["response_format"]["type"], "json_schema")
            return {
                "choices": [
                    {
                        "message": {
                            "content": """
                            {
                              "subject": "Physics",
                              "overall_summary": "One diagnosed Physics question was reviewed.",
                              "recurring_gaps": [],
                              "broader_related_patterns": [],
                              "chapter_topic_weakness_map": ["Kinematics / Projectile motion: early evidence."],
                              "isolated_gaps": ["Projectile components is an early indicator."],
                              "study_priorities": ["Review component-wise motion before mixed projectile problems."],
                              "teacher_intervention_notes": ["Check whether the student separates horizontal and vertical motion."],
                              "evidence_appendix": ["r1:q1: Projectile components."]
                            }
                            """
                        }
                    }
                ]
            }

        writer = LiteLLMProfileReportWriter(
            model_config=FakeProfileReportModelConfig(),
            completion_fn=completion_fn,
        )
        report = ProfileAnalysisService(report_writer=writer).generate(pack)

        validate_profile_report(report, pack)
        self.assertIn("component-wise motion", report.study_priorities[0])

    def test_invalid_llm_report_falls_back_to_deterministic_report(self):
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

        class InvalidWriter:
            def write(self, _pack):
                raise ValueError("bad model output")

        report = ProfileAnalysisService(report_writer=InvalidWriter()).generate(pack)

        validate_profile_report(report, pack)
        self.assertIn("Analyzed 1 diagnosed questions", report.overall_summary)


class FakeModelSettings:
    def to_litellm_kwargs(self):
        return {"model": "fake/profile-report", "timeout": 3}


class FakeProfileReportModelConfig:
    def resolve(self):
        return FakeModelSettings()


if __name__ == "__main__":
    unittest.main()
