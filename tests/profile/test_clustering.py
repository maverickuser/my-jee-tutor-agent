import math
import unittest

from pydantic import ValidationError

from jee_tutor.profile.clustering import (
    EvidenceNeighborPair,
    build_mutual_neighbor_pairs,
    cosine_similarity,
)
from jee_tutor.profile.embeddings import EvidenceEmbeddingRecord
from tests.profile.test_semantic_evidence_pack import evidence


class MutualNeighborClusteringTest(unittest.TestCase):
    def test_returns_only_reciprocal_top_k_neighbors(self):
        items = [
            evidence("a:q1", "a"),
            evidence("b:q1", "b"),
            evidence("c:q1", "c"),
        ]
        records = _embedding_records(
            {
                "a:q1": _unit_vector(0.0),
                "b:q1": _unit_vector(0.1),
                "c:q1": _unit_vector(-0.05),
            }
        )

        pairs = build_mutual_neighbor_pairs(
            evidence_items=items,
            embedding_records=records,
            chapter_family="Kinematics",
            similarity_floor=0.0,
            max_neighbors=1,
        )

        self.assertEqual(
            [(pair.left_evidence_id, pair.right_evidence_id) for pair in pairs],
            [("a:q1", "c:q1")],
        )
        self.assertEqual(pairs[0].left_neighbor_rank, 1)
        self.assertEqual(pairs[0].right_neighbor_rank, 1)

    def test_applies_absolute_similarity_floor(self):
        items = [evidence("a:q1", "a"), evidence("b:q1", "b")]

        pairs = build_mutual_neighbor_pairs(
            evidence_items=items,
            embedding_records=_embedding_records(
                {"a:q1": [1.0, 0.0], "b:q1": [0.0, 1.0]}
            ),
            chapter_family="Kinematics",
            similarity_floor=0.5,
            max_neighbors=1,
        )

        self.assertEqual(pairs, [])

    def test_breaks_similarity_ties_by_evidence_id(self):
        items = [
            evidence("a:q1", "a"),
            evidence("b:q1", "b"),
            evidence("c:q1", "c"),
        ]

        pairs = build_mutual_neighbor_pairs(
            evidence_items=items,
            embedding_records=_embedding_records(
                {
                    "a:q1": [1.0, 0.0],
                    "b:q1": [0.0, 1.0],
                    "c:q1": [0.0, -1.0],
                }
            ),
            chapter_family="Kinematics",
            similarity_floor=-1.0,
            max_neighbors=1,
        )

        self.assertEqual(
            [(pair.left_evidence_id, pair.right_evidence_id) for pair in pairs],
            [("a:q1", "b:q1")],
        )

    def test_bridge_item_does_not_create_a_transitive_candidate(self):
        items = [
            evidence("a:q1", "a"),
            evidence("b:q1", "b"),
            evidence("c:q1", "c"),
        ]

        pairs = build_mutual_neighbor_pairs(
            evidence_items=items,
            embedding_records=_embedding_records(
                {
                    "a:q1": _unit_vector(0.0),
                    "b:q1": _unit_vector(0.1),
                    "c:q1": _unit_vector(0.2),
                }
            ),
            chapter_family="Kinematics",
            similarity_floor=0.98,
            max_neighbors=1,
        )

        self.assertEqual(
            [(pair.left_evidence_id, pair.right_evidence_id) for pair in pairs],
            [("a:q1", "b:q1")],
        )

    def test_validates_configuration_and_embedding_inputs(self):
        item = evidence("a:q1", "a")
        record = _embedding_records({"a:q1": [1.0, 0.0]})

        with self.assertRaisesRegex(ValueError, "max_neighbors"):
            build_mutual_neighbor_pairs(
                evidence_items=[item],
                embedding_records=record,
                chapter_family="Kinematics",
                similarity_floor=0.5,
                max_neighbors=0,
            )
        with self.assertRaisesRegex(ValueError, "similarity_floor"):
            build_mutual_neighbor_pairs(
                evidence_items=[item],
                embedding_records=record,
                chapter_family="Kinematics",
                similarity_floor=1.1,
                max_neighbors=1,
            )
        with self.assertRaisesRegex(ValueError, "Missing embeddings"):
            build_mutual_neighbor_pairs(
                evidence_items=[item],
                embedding_records={},
                chapter_family="Kinematics",
                similarity_floor=0.5,
                max_neighbors=1,
            )
        with self.assertRaisesRegex(ValueError, "unique evidence ids"):
            build_mutual_neighbor_pairs(
                evidence_items=[item, item],
                embedding_records=record,
                chapter_family="Kinematics",
                similarity_floor=0.5,
                max_neighbors=1,
            )
        with self.assertRaisesRegex(ValueError, "same dimensions"):
            cosine_similarity([1.0], [1.0, 0.0])
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 0.0]), 0.0)

    def test_candidate_pair_is_immutable_and_canonically_ordered(self):
        pair = EvidenceNeighborPair(
            pair_id="pair-1",
            left_evidence_id="a:q1",
            right_evidence_id="b:q1",
            chapter_family="Kinematics",
            cosine_similarity=0.9,
            left_neighbor_rank=1,
            right_neighbor_rank=1,
        )

        with self.assertRaises(ValidationError):
            pair.cosine_similarity = 0.8
        with self.assertRaisesRegex(ValidationError, "lexically ordered"):
            EvidenceNeighborPair(
                pair_id="pair-2",
                left_evidence_id="b:q1",
                right_evidence_id="a:q1",
                chapter_family="Kinematics",
                cosine_similarity=0.9,
                left_neighbor_rank=1,
                right_neighbor_rank=1,
            )


def _unit_vector(angle: float) -> list[float]:
    return [math.cos(angle), math.sin(angle)]


def _embedding_records(
    vectors: dict[str, list[float]],
) -> dict[str, EvidenceEmbeddingRecord]:
    return {
        evidence_id: EvidenceEmbeddingRecord(
            diagnosis_json_s3_uri=f"s3://bucket/{evidence_id}.json",
            embedding_key=f"{evidence_id}#fake#v2",
            evidence_id=evidence_id,
            embedding_model="fake",
            embedding_input_version="v2",
            embedding_text_hash="hash",
            embedding=vector,
            created_at="2026-07-28T00:00:00+00:00",
        )
        for evidence_id, vector in vectors.items()
    }


if __name__ == "__main__":
    unittest.main()
