import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from jee_tutor.profile.clustering import EvidenceNeighborPair
from jee_tutor.profile.evidence import ProfileEvidenceItem
from jee_tutor.profile.hierarchical import (
    CandidateRelationshipDecision,
    ConceptualStrand,
    ConceptualStrandOutput,
    LiteLLMConceptualStrandClassifier,
    StrandManifestation,
    discard_unsupported_strands,
    recurring_conceptual_strands,
    repair_conceptual_strand_output,
    validate_candidate_relationships,
    validate_conceptual_strand_output,
)
from jee_tutor.profile.model_config import ProfileClassifierModelConfig


class ConceptualStrandTest(unittest.TestCase):
    def test_recurring_requires_two_independent_reports_and_non_low_confidence(self):
        items = [evidence("r1", "q1"), evidence("r2", "q1")]
        index = {item.evidence_id: item for item in items}
        strand = conceptual_strand(items)

        recurring = recurring_conceptual_strands([strand], index)

        self.assertEqual(len(recurring), 1)
        self.assertEqual(recurring[0].diagnosis_report_count, 2)
        self.assertEqual(recurring[0].question_count, 2)
        self.assertEqual(
            recurring_conceptual_strands(
                [strand.model_copy(update={"confidence": "low"})], index
            ),
            [],
        )

    def test_relationship_validation_rejects_missing_duplicate_and_unknown_pairs(self):
        pair = candidate_pair()
        with self.assertRaisesRegex(ValueError, "missing pair ids"):
            validate_candidate_relationships([], [pair])
        with self.assertRaisesRegex(ValueError, "duplicate pair ids"):
            validate_candidate_relationships(
                [relationship(pair.pair_id), relationship(pair.pair_id)], [pair]
            )
        with self.assertRaisesRegex(ValueError, "unknown pair ids"):
            validate_candidate_relationships([relationship("invented")], [pair])

    def test_repair_drops_unknown_ids_and_restores_manifestations(self):
        items = [evidence("r1", "q1"), evidence("r2", "q1")]
        strand = conceptual_strand(items).model_copy(
            update={
                "evidence_ids": [items[0].evidence_id, "invented"],
                "manifestations": [],
            }
        )

        repaired = repair_conceptual_strand_output(
            ConceptualStrandOutput(strands=[strand]), items
        )

        self.assertEqual(repaired.strands[0].evidence_ids, [items[0].evidence_id])
        self.assertEqual(
            repaired.strands[0].manifestations[0].manifestation,
            items[0].exact_concept_gap,
        )
        validate_conceptual_strand_output(repaired, items)

    def test_discards_and_logs_disconnected_strand(self):
        items = [evidence("r1", "q1"), evidence("r2", "q1"), evidence("r3", "q1")]
        pair = candidate_pair()
        output = ConceptualStrandOutput(
            relationships=[relationship(pair.pair_id)],
            strands=[conceptual_strand(items)],
        )

        with self.assertLogs("jee_tutor.profile.hierarchical", level="WARNING") as logs:
            repaired = discard_unsupported_strands(output, candidate_pairs=[pair])

        self.assertEqual(repaired.strands, [])
        self.assertIn("reason=disconnected_same_gap_graph", logs.output[0])
        validate_conceptual_strand_output(repaired, items, candidate_pairs=[pair])

    def test_discards_and_logs_strand_with_contradictory_internal_pair(self):
        items = [evidence("r1", "q1"), evidence("r2", "q1"), evidence("r3", "q1")]
        same_pair = candidate_pair()
        contradictory_pair = same_pair.model_copy(
            update={
                "pair_id": "pair-2",
                "left_evidence_id": "r2:q1",
                "right_evidence_id": "r3:q1",
            }
        )
        output = ConceptualStrandOutput(
            relationships=[
                relationship(same_pair.pair_id),
                CandidateRelationshipDecision(
                    candidate_pair_id=contradictory_pair.pair_id,
                    relationship="related_but_distinct",
                    rationale="The questions require different corrective models.",
                ),
            ],
            strands=[conceptual_strand(items)],
        )

        with self.assertLogs("jee_tutor.profile.hierarchical", level="WARNING") as logs:
            repaired = discard_unsupported_strands(
                output,
                candidate_pairs=[same_pair, contradictory_pair],
            )

        self.assertEqual(repaired.strands, [])
        self.assertIn("reason=contradictory_internal_relationship", logs.output[0])
        validate_conceptual_strand_output(
            repaired,
            items,
            candidate_pairs=[same_pair, contradictory_pair],
        )

    def test_litellm_classifier_uses_strict_schema_and_evidence_payload(self):
        items = [evidence("r1", "q1"), evidence("r2", "q1")]
        output = ConceptualStrandOutput(
            relationships=[relationship(candidate_pair().pair_id)],
            strands=[conceptual_strand(items)],
        )
        captured = {}
        observability = RecordingObservability()

        def completion_fn(**kwargs):
            captured.update(kwargs)
            return {
                "choices": [{"message": {"content": output.model_dump_json()}}],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                },
            }

        classifier = LiteLLMConceptualStrandClassifier(
            model_config=ProfileClassifierModelConfig(
                environ={"PROFILE_SEMANTIC_CLUSTER_MODEL": "fake/model"},
                config={},
            ),
            observability=observability,
            completion_fn=completion_fn,
        )
        actual = classifier.classify(evidence_items=items, candidate_pairs=[candidate_pair()])

        self.assertEqual(actual, output)
        self.assertEqual(captured["temperature"], 0)
        self.assertTrue(
            captured["messages"][0]["content"].startswith(
                "You are an expert JEE educational diagnostician and cognitive "
                "learning specialist."
            )
        )
        self.assertTrue(captured["response_format"]["json_schema"]["strict"])
        payload = json.loads(captured["messages"][1]["content"])
        self.assertEqual(len(payload["evidence"]), 2)
        self.assertEqual(payload["candidate_pairs"][0]["pair_id"], candidate_pair().pair_id)
        self.assertEqual(
            observability.generation_kwargs["name"],
            "profile-conceptual-strand-classification",
        )
        self.assertEqual(observability.generation_kwargs["input_payload"]["evidence_count"], 2)
        self.assertNotIn("evidence", observability.generation_kwargs["input_payload"])
        self.assertEqual(
            observability.observation.updates[0]["usage_details"],
            {"input": 20, "output": 10, "total": 30},
        )
        self.assertEqual(
            observability.observation.updates[0]["output"]["validation_status"],
            "passed",
        )

    def test_classifier_model_config_resolves_provider_credentials_and_proxy(self):
        openai = ProfileClassifierModelConfig(
            environ={
                "PROFILE_SEMANTIC_CLUSTER_MODEL": "openai/gpt-4o",
                "OPENAI_API_KEY": "openai-key",
                "LITELLM_BASE_URL": "https://proxy.example",
            },
            config={"completion": {"temperature": 0}},
        ).resolve()
        self.assertEqual(openai.api_key, "openai-key")
        self.assertEqual(openai.api_base, "https://proxy.example")
        self.assertEqual(openai.to_litellm_kwargs()["temperature"], 0)

        custom = ProfileClassifierModelConfig(
            environ={
                "PROFILE_SEMANTIC_CLUSTER_MODEL": "custom/model",
                "LITELLM_API_KEY": "proxy-key",
            },
            config={"completion": "invalid"},
        ).resolve()
        self.assertEqual(custom.api_key, "proxy-key")
        self.assertNotIn("api_base", custom.to_litellm_kwargs())

        with patch.dict(
            "os.environ",
            {"PROFILE_SEMANTIC_CLUSTER_MODEL": "gemini/from-ci"},
            clear=True,
        ):
            configured = ProfileClassifierModelConfig(
                environ={},
                config={"semantic_clustering": {"model": "gemini/configured"}},
            ).resolve()
        self.assertEqual(configured.model, "gemini/configured")

    def test_classifier_records_safe_failure_in_generation_trace(self):
        observability = RecordingObservability()

        def completion_fn(**_kwargs):
            raise RuntimeError("provider unavailable")

        classifier = LiteLLMConceptualStrandClassifier(
            model_config=ProfileClassifierModelConfig(
                environ={"PROFILE_SEMANTIC_CLUSTER_MODEL": "fake/model"},
                config={},
            ),
            observability=observability,
            completion_fn=completion_fn,
        )

        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            classifier.classify(
                evidence_items=[evidence("r1", "q1"), evidence("r2", "q1")],
                candidate_pairs=[candidate_pair()],
            )

        self.assertEqual(
            observability.observation.updates[0]["output"],
            {"validation_status": "failed", "error_type": "RuntimeError"},
        )


class RecordingObservation:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class RecordingObservability:
    def __init__(self):
        self.generation_kwargs = None
        self.observation = RecordingObservation()

    @contextmanager
    def generation_span(self, **kwargs):
        self.generation_kwargs = kwargs
        yield self.observation


def evidence(report_id: str, question: str) -> ProfileEvidenceItem:
    return ProfileEvidenceItem(
        evidence_id=f"{report_id}:{question}",
        evidence_reference=f"Test : {question}",
        diagnosis_report_id=report_id,
        diagnosis_json_s3_uri=f"s3://bucket/{report_id}.json",
        subject="Physics",
        test_name="Test",
        diagnosis_date="2026-01-01T00:00:00Z",
        question_number=question,
        chapter="Kinematics",
        topic="Projectile motion",
        exact_concept_gap="Projectile components",
        likely_thought="Treated the motion as one-dimensional.",
        why_wrong="Horizontal and vertical motion must be resolved separately.",
        deep_dive_recommendation="Resolve vector components.",
    )


def conceptual_strand(items) -> ConceptualStrand:
    return ConceptualStrand(
        strand_id="components",
        chapter_family="Kinematics",
        chapter_labels=["Kinematics"],
        topics=["Projectile motion"],
        title="Resolve components",
        missing_mental_model="Independent components",
        shared_failure="Treats vector motion as scalar motion",
        corrective_model="Resolve horizontal and vertical components",
        evidence_ids=[item.evidence_id for item in items],
        manifestations=[
            StrandManifestation(
                evidence_id=item.evidence_id,
                manifestation="Did not resolve components",
            )
            for item in items
        ],
        confidence="high",
        rationale="One model prevents both failures.",
    )


def candidate_pair() -> EvidenceNeighborPair:
    return EvidenceNeighborPair(
        pair_id="pair-1",
        chapter_family="Kinematics",
        left_evidence_id="r1:q1",
        right_evidence_id="r2:q1",
        cosine_similarity=0.9,
        left_neighbor_rank=1,
        right_neighbor_rank=1,
    )


def relationship(pair_id: str) -> CandidateRelationshipDecision:
    return CandidateRelationshipDecision(
        candidate_pair_id=pair_id,
        relationship="same_underlying_gap",
        rationale="One missing component model.",
    )


if __name__ == "__main__":
    unittest.main()
