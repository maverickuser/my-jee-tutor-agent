import unittest

from jee_tutor.profile.hierarchical import (
    BroaderConceptualPattern,
    BroaderPatternManifestation,
    LocalConceptGap,
    build_longitudinal_evidence_pack,
)
from jee_tutor.profile.reporting import ProfileAnalysisService, validate_profile_report
from tests.profile.test_semantic_evidence_pack import evidence


def local_gap(
    gap_id: str,
    evidence_ids: list[str],
    *,
    chapter: str = "Kinematics",
    topic: str = "Projectile motion",
) -> LocalConceptGap:
    return LocalConceptGap(
        gap_id=gap_id,
        canonical_chapter=chapter,
        canonical_topic=topic,
        required_concept="Resolve motion into independent components.",
        concept_gap="Projectile components",
        shared_misconception="projectile speed remains constant",
        corrective_concept="apply acceleration to the vertical component",
        evidence_ids=evidence_ids,
        confidence="high",
        rationale="Every item uses the same constant-speed misconception.",
    )


class ProfileReportingTest(unittest.TestCase):
    def test_report_contains_only_agreed_sections_and_embedded_actions(self):
        items = [evidence("r1:q1", "r1"), evidence("r2:q1", "r2")]
        pack = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=items,
            local_gaps=[local_gap("gap-1", ["r1:q1", "r2:q1"])],
            broader_patterns=[],
        )

        report = ProfileAnalysisService().generate(pack)
        markdown = ProfileAnalysisService.render_markdown(report)

        validate_profile_report(report, pack)
        self.assertEqual(report.recurring_gaps[0].diagnosis_report_count, 2)
        self.assertIn("vertical component", report.recurring_gaps[0].student_action)
        self.assertIn("constant", report.recurring_gaps[0].teacher_action)
        self.assertIn("## Overall Summary", markdown)
        self.assertIn("## Recurring Gaps", markdown)
        self.assertIn("## Broader Related Patterns", markdown)
        self.assertIn("## Evidence Appendix", markdown)
        self.assertNotIn("Study Priorities", markdown)
        self.assertNotIn("Teacher Intervention Notes", markdown)
        self.assertNotIn("Weakness Map", markdown)

    def test_broader_pattern_references_distinct_local_gaps(self):
        items = [
            evidence("r1:q1", "r1"),
            evidence("r2:q1", "r2"),
            evidence(
                "r3:q1",
                "r3",
                chapter="Electrostatics",
                topic="Electric fields",
            ),
            evidence(
                "r4:q1",
                "r4",
                chapter="Electrostatics",
                topic="Electric fields",
            ),
        ]
        gaps = [
            local_gap("motion", ["r1:q1", "r2:q1"]),
            local_gap(
                "fields",
                ["r3:q1", "r4:q1"],
                chapter="Electrostatics",
                topic="Electric fields",
            ),
        ]
        pattern = BroaderConceptualPattern(
            pattern_id="vectors",
            title="Vector direction before calculation",
            shared_reasoning_gap="Direction is not established before combining vectors.",
            common_corrective_principle="draw and label every vector before calculation",
            component_gap_ids=["motion", "fields"],
            manifestations=[
                BroaderPatternManifestation(
                    gap_id="motion",
                    chapter="Kinematics",
                    topic="Projectile motion",
                    manifestation="motion components are not resolved",
                ),
                BroaderPatternManifestation(
                    gap_id="fields",
                    chapter="Electrostatics",
                    topic="Electric fields",
                    manifestation="field contributions are combined without direction",
                ),
            ],
            confidence="high",
            rationale="Both gaps omit vector representation before calculation.",
        )
        pack = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=items,
            local_gaps=gaps,
            broader_patterns=[pattern],
        )

        report = ProfileAnalysisService().generate(pack)

        self.assertEqual(report.broader_related_patterns[0].chapter_count, 2)
        self.assertEqual(
            report.broader_related_patterns[0].component_gap_ids,
            ["motion", "fields"],
        )

    def test_appendix_requires_exact_evidence_coverage(self):
        items = [evidence("r1:q1", "r1")]
        pack = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=items,
            local_gaps=[local_gap("gap-1", ["r1:q1"])],
            broader_patterns=[],
        )
        report = ProfileAnalysisService().generate(pack)
        report.evidence_appendix = []

        with self.assertRaisesRegex(ValueError, "appendix"):
            validate_profile_report(report, pack)


if __name__ == "__main__":
    unittest.main()
