import json
import unittest

from jee_tutor.profile.embeddings import EvidenceEmbeddingRecord
from jee_tutor.profile.hierarchical import (
    BroaderConceptualPattern,
    BroaderPatternAnalyzer,
    BroaderPatternManifestation,
    ConceptualStrand,
    ConceptualStrandOutput,
    EvidenceExclusion,
    LiteLLMBroaderPatternClassifier,
    LiteLLMConceptualStrandClassifier,
    StrandManifestation,
    ValidatedRecurringStrand,
    build_longitudinal_evidence_pack,
    build_strand_candidate_clusters,
    normalize_chapter_family,
    repair_conceptual_strand_output,
    recurring_conceptual_strands,
    validate_broader_patterns,
    validate_conceptual_strand_output,
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


def strand(
    strand_id: str,
    evidence_ids: list[str],
    *,
    family: str = "Electrostatics and Capacitance",
    confidence: str = "high",
) -> ConceptualStrand:
    return ConceptualStrand(
        strand_id=strand_id,
        chapter_family=family,
        chapter_labels=["Electrostatics", "Electrostatics and Capacitance"],
        topics=["Capacitor circuits", "Charge redistribution"],
        title="Capacitor state modeling",
        missing_mental_model=(
            "Identify electrical nodes, conserved charge, and final voltage constraints."
        ),
        shared_failure="Applies a local formula before constructing the circuit state.",
        corrective_model=(
            "Mark isolated nodes, conserve their charge, then impose equilibrium voltage."
        ),
        evidence_ids=evidence_ids,
        manifestations=[
            StrandManifestation(
                evidence_id=evidence_id,
                manifestation=f"Manifestation for {evidence_id}.",
            )
            for evidence_id in evidence_ids
        ],
        confidence=confidence,
        rationale="One node-and-equilibrium model corrects every manifestation.",
    )


class HierarchicalProfileTest(unittest.TestCase):
    def test_normalizes_related_chapter_labels_but_not_unrelated_families(self):
        self.assertEqual(
            normalize_chapter_family("Electrostatics"),
            "Electrostatics and Capacitance",
        )
        self.assertEqual(
            normalize_chapter_family("Electrostatics and Capacitance"),
            "Electrostatics and Capacitance",
        )
        self.assertNotEqual(
            normalize_chapter_family("Current Electricity"),
            "Electrostatics and Capacitance",
        )

    def test_candidates_cross_topics_inside_family_not_chapter_families(self):
        items = [
            evidence(
                "r1:q1",
                "r1",
                chapter="Electrostatics",
                topic="Capacitor circuits",
            ),
            evidence(
                "r2:q1",
                "r2",
                chapter="Electrostatics and Capacitance",
                topic="Charge redistribution",
            ),
            evidence(
                "r3:q1",
                "r3",
                chapter="Current Electricity",
                topic="Potentiometer",
            ),
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

        candidates = build_strand_candidate_clusters(
            evidence_items=items,
            embedding_records=records,
            similarity_threshold=0.5,
        )

        self.assertEqual(
            [candidate.evidence_ids for candidate in candidates],
            [["r1:q1", "r2:q1"], ["r3:q1"]],
        )

    def test_strand_requires_manifestation_for_every_evidence_item(self):
        items = [
            evidence("r1:q1", "r1", chapter="Electrostatics"),
            evidence("r2:q1", "r2", chapter="Electrostatics"),
        ]
        invalid = strand("strand-1", ["r1:q1", "r2:q1"])
        invalid.manifestations.pop()

        with self.assertRaisesRegex(ValueError, "exactly cover"):
            validate_conceptual_strand_output(
                ConceptualStrandOutput(strands=[invalid]), items
            )

    def test_strand_rejects_cross_family_evidence(self):
        items = [
            evidence("r1:q1", "r1", chapter="Electrostatics"),
            evidence("r2:q1", "r2", chapter="Current Electricity"),
        ]

        with self.assertRaisesRegex(ValueError, "multiple chapter families"):
            validate_conceptual_strand_output(
                ConceptualStrandOutput(
                    strands=[strand("strand-1", ["r1:q1", "r2:q1"])]
                ),
                items,
            )

    def test_recurrence_requires_independent_reports_and_confidence(self):
        items = [
            evidence("r1:q1", "r1"),
            evidence("r1:q2", "r1"),
            evidence("r2:q1", "r2"),
        ]
        index = {item.evidence_id: item for item in items}

        self.assertEqual(
            recurring_conceptual_strands(
                [strand("one-paper", ["r1:q1", "r1:q2"])], index
            ),
            [],
        )
        self.assertEqual(
            recurring_conceptual_strands(
                [
                    strand(
                        "low-confidence",
                        ["r1:q1", "r2:q1"],
                        confidence="low",
                    )
                ],
                index,
            ),
            [],
        )
        recurring = recurring_conceptual_strands(
            [strand("recurring", ["r1:q1", "r2:q1"])], index
        )
        self.assertEqual(recurring[0].diagnosis_report_count, 2)

    def test_non_conceptual_exclusion_is_preserved_for_audit(self):
        item = evidence("r1:q1", "r1")
        output = ConceptualStrandOutput(
            exclusions=[
                EvidenceExclusion(
                    evidence_id=item.evidence_id,
                    reason="calculation_execution",
                    rationale="The model and setup were correct.",
                )
            ]
        )

        validated = validate_conceptual_strand_output(output, [item])

        self.assertEqual(validated.exclusions[0].reason, "calculation_execution")

    def test_repairs_invented_ids_and_cross_family_membership(self):
        items = [
            evidence(
                "006445c3-c90d-47fa-985f-b799c78d390e:q12",
                "006445c3-c90d-47fa-985f-b799c78d390e",
                chapter="Electrostatics",
                topic="Capacitor circuits",
            ),
            evidence(
                "227ac774-ba13-4e11-a1e4-6d25d993c1a7:q6",
                "227ac774-ba13-4e11-a1e4-6d25d993c1a7",
                chapter="Electrostatics and Capacitance",
                topic="Charge redistribution",
            ),
            evidence(
                "current-report:q1",
                "current-report",
                chapter="Current Electricity",
                topic="Potentiometer",
            ),
        ]
        malformed = strand(
            "strand-1",
            [
                items[0].evidence_id,
                "006445c3-c90d-47fa-985f-b799c78d390e:q2",
                items[1].evidence_id,
                items[2].evidence_id,
                "227ac774-ba13-4e11-a1e4-6d25d993c1a7:q1",
            ],
        )
        malformed.manifestations = [
            StrandManifestation(
                evidence_id=items[0].evidence_id,
                manifestation="Used one capacitor's charge as total battery charge.",
            ),
            StrandManifestation(
                evidence_id="006445c3-c90d-47fa-985f-b799c78d390e:q2",
                manifestation="Invented question.",
            ),
            StrandManifestation(
                evidence_id=items[2].evidence_id,
                manifestation="Unrelated current-electricity manifestation.",
            ),
        ]
        output = ConceptualStrandOutput(
            strands=[malformed],
            exclusions=[
                EvidenceExclusion(
                    evidence_id="unknown:q4",
                    reason="insufficient_evidence",
                    rationale="Invented exclusion.",
                ),
                EvidenceExclusion(
                    evidence_id=items[0].evidence_id,
                    reason="unrelated_misconception",
                    rationale="Conflicts with assigned evidence.",
                ),
            ],
        )

        repaired = repair_conceptual_strand_output(output, items)
        validated = validate_conceptual_strand_output(repaired, items)

        self.assertEqual(
            validated.strands[0].evidence_ids,
            [items[0].evidence_id, items[1].evidence_id],
        )
        self.assertEqual(
            validated.strands[0].chapter_family,
            "Electrostatics and Capacitance",
        )
        self.assertEqual(
            validated.strands[0].topics,
            ["Capacitor circuits", "Charge redistribution"],
        )
        self.assertEqual(
            validated.strands[0].manifestations[1].manifestation,
            items[1].exact_concept_gap,
        )
        self.assertEqual(validated.exclusions, [])

    def test_drops_strand_when_classifier_invents_every_evidence_id(self):
        malformed = strand("strand-1", ["unknown:q1"])

        repaired = repair_conceptual_strand_output(
            ConceptualStrandOutput(strands=[malformed]),
            [evidence("r1:q1", "r1")],
        )

        self.assertEqual(repaired.strands, [])

    def test_broader_pattern_requires_distinct_families(self):
        items = [
            evidence("r1:q1", "r1"),
            evidence("r2:q1", "r2"),
            evidence("r3:q1", "r3"),
            evidence("r4:q1", "r4"),
        ]
        index = {item.evidence_id: item for item in items}
        recurring = recurring_conceptual_strands(
            [
                strand("strand-1", ["r1:q1", "r2:q1"]),
                strand("strand-2", ["r3:q1", "r4:q1"]),
            ],
            index,
        )
        pattern = BroaderConceptualPattern(
            pattern_id="pattern-1",
            title="Premature equation selection",
            shared_reasoning_gap="Selects equations before establishing constraints.",
            common_corrective_principle="State the model and constraints first.",
            component_strand_ids=["strand-1", "strand-2"],
            manifestations=[
                BroaderPatternManifestation(
                    strand_id="strand-1",
                    chapter_family="Electrostatics and Capacitance",
                    manifestation="Capacitor circuit state.",
                ),
                BroaderPatternManifestation(
                    strand_id="strand-2",
                    chapter_family="Electrostatics and Capacitance",
                    manifestation="Another capacitor state.",
                ),
            ],
            confidence="high",
            rationale="Same family is not broad.",
        )

        with self.assertRaisesRegex(ValueError, "distinct chapter families"):
            validate_broader_patterns([pattern], recurring)

    def test_evidence_pack_preserves_recurring_strand_and_exclusions(self):
        items = [evidence("r1:q1", "r1"), evidence("r2:q1", "r2")]
        output = ConceptualStrandOutput(
            strands=[strand("strand-1", ["r1:q1", "r2:q1"])]
        )

        pack = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=items,
            strand_output=output,
            broader_patterns=[],
        )

        self.assertEqual(pack.recurring_strands[0].strand.strand_id, "strand-1")
        self.assertEqual(pack.evidence_index["r1:q1"].test_date, "2026-07-18")

    def test_litellm_classifier_returns_strands_and_strict_schema(self):
        item = evidence("r1:q1", "r1")
        candidate = SemanticCandidateCluster(
            candidate_id="candidate-1",
            evidence_ids=["r1:q1"],
            rationale="Chapter family: Electrostatics and Capacitance.",
        )
        output = ConceptualStrandOutput(
            strands=[strand("strand-1", ["r1:q1"])]
        )
        captured = {}

        def completion_fn(**kwargs):
            captured.update(kwargs)
            return {
                "choices": [
                    {"message": {"content": json.dumps(output.model_dump())}}
                ]
            }

        actual = LiteLLMConceptualStrandClassifier(
            model_config=FakeModelConfig(),
            completion_fn=completion_fn,
        ).classify(evidence_items=[item], candidates=[candidate])

        self.assertEqual(actual, output)
        self.assertEqual(captured["num_retries"], 0)
        self.assertTrue(captured["response_format"]["json_schema"]["strict"])
        self.assertIn("chapter_family", captured["messages"][1]["content"])

    def test_litellm_broader_classifier_uses_recurring_strand_contract(self):
        first = ValidatedRecurringStrand(
            strand=strand("strand-1", ["r1:q1", "r2:q1"]),
            diagnosis_report_count=2,
            question_count=2,
        )
        second_strand = strand(
            "strand-2",
            ["r3:q1", "r4:q1"],
            family="Current Electricity",
        )
        second_strand.chapter_labels = ["Current Electricity"]
        second = ValidatedRecurringStrand(
            strand=second_strand,
            diagnosis_report_count=2,
            question_count=2,
        )
        candidate = SemanticCandidateCluster(
            candidate_id="candidate-1",
            evidence_ids=["strand-1", "strand-2"],
            rationale="Possible transferable reasoning operation.",
        )
        pattern = BroaderConceptualPattern(
            pattern_id="BRP-1",
            title="Equations before constraints",
            shared_reasoning_gap="Selects equations before establishing constraints.",
            common_corrective_principle="Represent constraints before equation selection.",
            component_strand_ids=["strand-1", "strand-2"],
            manifestations=[
                BroaderPatternManifestation(
                    strand_id="strand-1",
                    chapter_family="Electrostatics and Capacitance",
                    manifestation="Does not construct capacitor node state.",
                ),
                BroaderPatternManifestation(
                    strand_id="strand-2",
                    chapter_family="Current Electricity",
                    manifestation="Does not construct loaded network topology.",
                ),
            ],
            confidence="high",
            rationale="The same pre-equation reasoning operation is absent.",
        )
        captured = {}

        def completion_fn(**kwargs):
            captured.update(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"patterns": [pattern.model_dump()]}
                            )
                        }
                    }
                ]
            }

        actual = LiteLLMBroaderPatternClassifier(
            model_config=FakeModelConfig(),
            completion_fn=completion_fn,
        ).classify(
            recurring_strands=[first, second],
            candidates=[candidate],
        )

        self.assertEqual(actual, [pattern])
        self.assertEqual(captured["num_retries"], 0)
        self.assertIn("recurring_strands", captured["messages"][1]["content"])
        self.assertEqual(
            captured["response_format"]["json_schema"]["name"],
            "student_profile_broader_patterns",
        )

    def test_broader_analyzer_builds_candidates_from_recurring_strands(self):
        evidence_items = [
            evidence("r1:q1", "r1", chapter="Electrostatics"),
            evidence("r2:q1", "r2", chapter="Electrostatics"),
            evidence("r3:q1", "r3", chapter="Current Electricity"),
            evidence("r4:q1", "r4", chapter="Current Electricity"),
        ]
        evidence_index = {
            item.evidence_id: item for item in evidence_items
        }
        first = ValidatedRecurringStrand(
            strand=strand("strand-1", ["r1:q1", "r2:q1"]),
            diagnosis_report_count=2,
            question_count=2,
        )
        second_strand = strand(
            "strand-2",
            ["r3:q1", "r4:q1"],
            family="Current Electricity",
        )
        second_strand.chapter_labels = ["Current Electricity"]
        second = ValidatedRecurringStrand(
            strand=second_strand,
            diagnosis_report_count=2,
            question_count=2,
        )
        pattern = BroaderConceptualPattern(
            pattern_id="BRP-1",
            title="Equations before constraints",
            shared_reasoning_gap="Selects equations before establishing constraints.",
            common_corrective_principle="Represent constraints before equation selection.",
            component_strand_ids=["strand-1", "strand-2"],
            manifestations=[
                BroaderPatternManifestation(
                    strand_id="strand-1",
                    chapter_family="Electrostatics and Capacitance",
                    manifestation="Capacitor state is not constructed.",
                ),
                BroaderPatternManifestation(
                    strand_id="strand-2",
                    chapter_family="Current Electricity",
                    manifestation="Loaded topology is not constructed.",
                ),
            ],
            confidence="high",
            rationale="Both fail before selecting an equation.",
        )
        classifier = FixedBroaderClassifier(pattern)

        actual = BroaderPatternAnalyzer(
            embedding_service=SyntheticEmbeddingService(),
            classifier=classifier,
            similarity_threshold=0.5,
        ).analyze(
            [first, second],
            evidence_index=evidence_index,
            subject="Physics",
        )

        self.assertEqual(actual, [pattern])
        self.assertEqual(
            classifier.candidates[0].evidence_ids,
            ["strand-1", "strand-2"],
        )


class SyntheticEmbeddingService:
    def ensure_embeddings(self, *, subject, evidence_items):
        return {
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
            for item in evidence_items
        }


class FixedBroaderClassifier:
    def __init__(self, pattern):
        self.pattern = pattern
        self.candidates = []

    def classify(self, *, recurring_strands, candidates):
        self.candidates = candidates
        return [self.pattern]


if __name__ == "__main__":
    unittest.main()
