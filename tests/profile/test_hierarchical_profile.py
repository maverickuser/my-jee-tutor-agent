import json
import unittest

from jee_tutor.profile.embeddings import EvidenceEmbeddingRecord
from jee_tutor.profile.hierarchical import (
    BroaderConceptualPattern,
    BroaderPatternManifestation,
    LiteLLMBroaderPatternClassifier,
    LiteLLMLocalGapClassifier,
    LocalConceptGap,
    build_local_candidate_clusters,
    build_longitudinal_evidence_pack,
    recurring_local_gaps,
    validate_broader_patterns,
    validate_local_gaps,
)
from jee_tutor.profile.semantic import (
    SemanticCandidateCluster,
    SemanticClusterModelSettings,
)
from tests.profile.test_semantic_evidence_pack import evidence


class FakeModelConfig:
    def resolve(self):
        return SemanticClusterModelSettings(
            model="fake/hierarchical",
            completion_options={},
        )


def gap(
    gap_id: str,
    evidence_ids: list[str],
    *,
    chapter: str,
    topic: str,
    confidence: str = "high",
) -> LocalConceptGap:
    return LocalConceptGap(
        gap_id=gap_id,
        canonical_chapter=chapter,
        canonical_topic=topic,
        required_concept="required concept",
        concept_gap=f"{gap_id} concept gap",
        shared_misconception="shared misconception",
        corrective_concept="one corrective concept",
        evidence_ids=evidence_ids,
        confidence=confidence,
        rationale="One concept, misconception, and correction apply to every item.",
    )


class HierarchicalProfileTest(unittest.TestCase):
    def test_litellm_classifiers_use_strict_structured_outputs(self):
        item = evidence("r1:q1", "r1")
        candidate = SemanticCandidateCluster(
            candidate_id="candidate-1",
            evidence_ids=["r1:q1"],
            rationale="embedding candidate",
        )
        local = gap(
            "local-1",
            ["r1:q1"],
            chapter="Kinematics",
            topic="Projectile motion",
        )
        recurring = recurring_local_gaps(
            [
                gap(
                    "local-1",
                    ["r1:q1", "r2:q1"],
                    chapter="Kinematics",
                    topic="Projectile motion",
                )
            ],
            {
                "r1:q1": item,
                "r2:q1": evidence("r2:q1", "r2"),
            },
        )
        calls = []

        def completion_fn(**kwargs):
            calls.append(kwargs)
            if "local_concept_gaps" in kwargs["response_format"]["json_schema"]["name"]:
                content = {"gaps": [local.model_dump()]}
            else:
                pattern = BroaderConceptualPattern(
                    pattern_id="pattern-1",
                    title="Shared representation gap",
                    shared_reasoning_gap="Uses symbols without checking their meaning.",
                    common_corrective_principle="Define quantities before manipulating them.",
                    component_gap_ids=["local-1", "local-2"],
                    manifestations=[
                        BroaderPatternManifestation(
                            gap_id="local-1",
                            chapter="Kinematics",
                            topic="Projectile motion",
                            manifestation="Misreads velocity components.",
                        ),
                        BroaderPatternManifestation(
                            gap_id="local-2",
                            chapter="Electrostatics",
                            topic="Electric field",
                            manifestation="Misreads field-vector components.",
                        ),
                    ],
                    confidence="high",
                    rationale="The same representation failure occurs in two contexts.",
                )
                content = {"patterns": [pattern.model_dump()]}
            return {"choices": [{"message": {"content": json.dumps(content)}}]}

        model_config = FakeModelConfig()
        local_output = LiteLLMLocalGapClassifier(
            model_config=model_config,
            completion_fn=completion_fn,
        ).classify(evidence_items=[item], candidates=[candidate])
        broader_output = LiteLLMBroaderPatternClassifier(
            model_config=model_config,
            completion_fn=completion_fn,
        ).classify(recurring_gaps=recurring, candidates=[candidate])

        self.assertEqual(local_output, [local])
        self.assertEqual(broader_output[0].pattern_id, "pattern-1")
        self.assertEqual([call["num_retries"] for call in calls], [0, 0])
        self.assertTrue(
            all(call["response_format"]["json_schema"]["strict"] for call in calls)
        )
        self.assertIn("evidence", calls[0]["messages"][1]["content"])
        self.assertIn("recurring_gaps", calls[1]["messages"][1]["content"])

    def test_local_candidates_never_cross_chapter_topic_context(self):
        items = [
            evidence("r1:q1", "r1", chapter="Kinematics", topic="Motion"),
            evidence("r2:q1", "r2", chapter="Kinematics", topic="Motion"),
            evidence("r3:q1", "r3", chapter="Electrostatics", topic="Fields"),
        ]
        records = {
            item.evidence_id: EvidenceEmbeddingRecord(
                diagnosis_json_s3_uri=item.diagnosis_json_s3_uri,
                embedding_key=f"{item.evidence_id}#fake#v1",
                evidence_id=item.evidence_id,
                embedding_model="fake",
                embedding_input_version="v1",
                embedding_text_hash="hash",
                embedding=[1.0, 0.0],
                created_at="2026-07-18T00:00:00+00:00",
            )
            for item in items
        }

        candidates = build_local_candidate_clusters(
            evidence_items=items,
            embedding_records=records,
            similarity_threshold=0.5,
        )

        self.assertEqual(
            [candidate.evidence_ids for candidate in candidates],
            [["r1:q1", "r2:q1"], ["r3:q1"]],
        )

    def test_local_gap_rejects_cross_context_evidence(self):
        items = [
            evidence("r1:q1", "r1", chapter="Kinematics", topic="Motion"),
            evidence("r2:q1", "r2", chapter="Electrostatics", topic="Fields"),
        ]
        cross_context = gap(
            "bad",
            ["r1:q1", "r2:q1"],
            chapter="Kinematics",
            topic="Motion",
        )

        with self.assertRaisesRegex(ValueError, "multiple chapter/topic"):
            validate_local_gaps([cross_context], items)

    def test_recurrence_requires_two_reports_and_excludes_low_confidence(self):
        items = [
            evidence("r1:q1", "r1"),
            evidence("r1:q2", "r1"),
            evidence("r2:q1", "r2"),
        ]
        index = {item.evidence_id: item for item in items}
        gaps = [
            gap(
                "one-report",
                ["r1:q1", "r1:q2"],
                chapter="Kinematics",
                topic="Projectile motion",
            ),
            gap(
                "low",
                ["r1:q1", "r2:q1"],
                chapter="Kinematics",
                topic="Projectile motion",
                confidence="low",
            ),
        ]

        self.assertEqual(recurring_local_gaps(gaps, index), [])

    def test_broader_pattern_requires_distinct_contexts(self):
        items = [evidence("r1:q1", "r1"), evidence("r2:q1", "r2")]
        local = gap(
            "local",
            ["r1:q1", "r2:q1"],
            chapter="Kinematics",
            topic="Projectile motion",
        )
        recurring = recurring_local_gaps(
            [local],
            {item.evidence_id: item for item in items},
        )
        pattern = BroaderConceptualPattern(
            pattern_id="bad",
            title="bad",
            shared_reasoning_gap="same context only",
            common_corrective_principle="correction",
            component_gap_ids=["local", "local-copy"],
            manifestations=[
                BroaderPatternManifestation(
                    gap_id="local",
                    chapter="Kinematics",
                    topic="Projectile motion",
                    manifestation="one",
                ),
                BroaderPatternManifestation(
                    gap_id="local-copy",
                    chapter="Kinematics",
                    topic="Projectile motion",
                    manifestation="two",
                ),
            ],
            confidence="high",
            rationale="bad",
        )

        with self.assertRaisesRegex(ValueError, "unknown gap"):
            validate_broader_patterns([pattern], recurring)

    def test_evidence_pack_preserves_test_date_for_appendix(self):
        item = evidence("r1:q1", "r1")
        pack = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=[item],
            local_gaps=[],
            broader_patterns=[],
        )

        self.assertEqual(pack.evidence_index["r1:q1"].test_date, "2026-07-18")


if __name__ == "__main__":
    unittest.main()
