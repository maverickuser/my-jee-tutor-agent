import unittest

from jee_tutor.profile.evidence import ProfileEvidenceItem
from jee_tutor.profile.semantic import (
    SemanticGapAnalyzer,
    SemanticGapCluster,
    build_longitudinal_evidence_pack,
    validate_semantic_clusters,
)


def evidence(
    evidence_id: str,
    report_id: str,
    gap: str = "Projectile components",
    chapter: str = "Kinematics",
    topic: str = "Projectile motion",
) -> ProfileEvidenceItem:
    return ProfileEvidenceItem(
        evidence_id=evidence_id,
        diagnosis_report_id=report_id,
        question_number=evidence_id.rsplit("q", 1)[-1],
        chapter=chapter,
        topic=topic,
        exact_concept_gap=gap,
        likely_thought="You likely used constant speed.",
        why_wrong="Vertical acceleration changes velocity.",
        deep_dive_recommendation="Resolve horizontal and vertical motion.",
    )


class SemanticEvidencePackTest(unittest.TestCase):
    def test_cluster_validation_rejects_unknown_and_duplicate_evidence(self):
        items = [evidence("r1:q1", "r1")]

        with self.assertRaisesRegex(ValueError, "unknown evidence"):
            validate_semantic_clusters(
                [
                    SemanticGapCluster(
                        cluster_id="c1",
                        cluster_type="same_underlying_gap",
                        title="bad",
                        evidence_ids=["missing"],
                        rationale="bad",
                    )
                ],
                items,
            )

        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_semantic_clusters(
                [
                    SemanticGapCluster(
                        cluster_id="c1",
                        cluster_type="same_underlying_gap",
                        title="one",
                        evidence_ids=["r1:q1"],
                        rationale="one",
                    ),
                    SemanticGapCluster(
                        cluster_id="c2",
                        cluster_type="same_wrong_approach",
                        title="two",
                        evidence_ids=["r1:q1"],
                        rationale="two",
                    ),
                ],
                items,
            )

    def test_semantic_analyzer_groups_normalized_gap_text(self):
        items = [
            evidence("r1:q1", "r1", gap="Projectile components"),
            evidence("r2:q1", "r2", gap="projectile-components!"),
            evidence("r2:q2", "r2", gap="Circular motion"),
        ]

        clusters = SemanticGapAnalyzer().cluster(items)

        self.assertEqual(len(clusters), 2)
        self.assertEqual(
            sorted(len(cluster.evidence_ids) for cluster in clusters),
            [1, 2],
        )

    def test_evidence_pack_marks_recurrence_only_across_reports(self):
        items = [
            evidence("r1:q1", "r1"),
            evidence("r1:q2", "r1"),
            evidence("r2:q1", "r2"),
            evidence("r3:q1", "r3", gap="Circular motion"),
        ]
        clusters = [
            SemanticGapCluster(
                cluster_id="recurring",
                cluster_type="same_underlying_gap",
                title="Projectile components",
                evidence_ids=["r1:q1", "r1:q2", "r2:q1"],
                rationale="same gap",
            ),
            SemanticGapCluster(
                cluster_id="isolated",
                cluster_type="same_underlying_gap",
                title="Circular motion",
                evidence_ids=["r3:q1"],
                rationale="single report",
            ),
        ]

        pack = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=items,
            clusters=clusters,
        )

        by_id = {cluster.cluster.cluster_id: cluster for cluster in pack.clusters}
        self.assertEqual(by_id["recurring"].recurrence_label, "recurring")
        self.assertEqual(by_id["recurring"].diagnosis_report_count, 2)
        self.assertEqual(
            by_id["isolated"].recurrence_label,
            "isolated_or_early_indicator",
        )
        self.assertEqual(pack.diagnosis_report_count, 3)
        self.assertEqual(pack.question_count, 4)
        self.assertIn("r1:q1", pack.evidence_index)
        self.assertEqual(pack.chapter_topic_map[0].chapter, "Kinematics")

    def test_evidence_pack_serializes_without_losing_references(self):
        item = evidence("r1:q1", "r1")
        clusters = SemanticGapAnalyzer().cluster([item])

        payload = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=[item],
            clusters=clusters,
        ).model_dump()

        self.assertEqual(payload["evidence_index"]["r1:q1"]["diagnosis_report_id"], "r1")
        self.assertEqual(payload["clusters"][0]["question_count"], 1)


if __name__ == "__main__":
    unittest.main()
