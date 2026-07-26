import unittest

from jee_tutor.profile.hierarchical import (
    BroaderConceptualPattern,
    BroaderPatternManifestation,
    ConceptualStrand,
    LongitudinalEvidencePack,
    StrandManifestation,
    ValidatedRecurringStrand,
)
from jee_tutor.profile.reporting import (
    ProfileAnalysisService,
    validate_profile_report,
)
from tests.profile.test_semantic_evidence_pack import evidence


def capacitor_strand() -> ConceptualStrand:
    return ConceptualStrand(
        strand_id="RG-1",
        chapter_family="Electrostatics and Capacitance",
        chapter_labels=["Electrostatics", "Electrostatics and Capacitance"],
        topics=["Charge redistribution", "Circuit analysis with capacitors"],
        title="Capacitor state and charge accounting",
        missing_mental_model=(
            "A capacitor network must be modeled through nodes, conserved charge, "
            "and final voltage constraints."
        ),
        shared_failure=(
            "Uses a local capacitor quantity before constructing the complete circuit state."
        ),
        corrective_model=(
            "Mark isolated nodes, conserve node charge, and then apply final-equilibrium "
            "voltage constraints."
        ),
        evidence_ids=["r1:q1", "r2:q1", "r3:q1"],
        manifestations=[
            StrandManifestation(
                evidence_id="r1:q1",
                manifestation="Equated switch charge flow with one capacitor's charge change.",
            ),
            StrandManifestation(
                evidence_id="r2:q1",
                manifestation="Subtracted the full battery voltage at an internal node.",
            ),
            StrandManifestation(
                evidence_id="r3:q1",
                manifestation="Ignored redistribution over the dielectric-covered area.",
            ),
        ],
        confidence="high",
        rationale=(
            "All three errors are corrected by constructing nodes, conserved quantities, "
            "and final equilibrium before using formulas."
        ),
    )


def report_pack() -> LongitudinalEvidencePack:
    items = [
        evidence(
            "r1:q1",
            "r1",
            chapter="Electrostatics",
            topic="Charge redistribution",
        ),
        evidence(
            "r2:q1",
            "r2",
            chapter="Electrostatics and Capacitance",
            topic="Circuit analysis with capacitors",
        ),
        evidence(
            "r3:q1",
            "r3",
            chapter="Electrostatics",
            topic="Dielectrics and bound charge",
        ),
    ]
    return LongitudinalEvidencePack(
        subject="Physics",
        diagnosis_report_count=3,
        question_count=3,
        evidence_index={item.evidence_id: item for item in items},
        recurring_strands=[
            ValidatedRecurringStrand(
                strand=capacitor_strand(),
                diagnosis_report_count=3,
                question_count=3,
            )
        ],
    )


class ProfileReportingTest(unittest.TestCase):
    def test_report_turns_physics_evidence_into_longitudinal_insight(self):
        report = ProfileAnalysisService().generate(report_pack())

        self.assertEqual(report.overall_summary.primary_strand_ids, ["RG-1"])
        self.assertIn(
            "Capacitor state and charge accounting",
            report.overall_summary.synthesis,
        )
        self.assertIn("different manifestations", report.overall_summary.significance)
        self.assertEqual(report.recurring_gaps[0].diagnosis_report_count, 3)
        self.assertEqual(len(report.recurring_gaps[0].manifestations), 3)
        self.assertIn("unfamiliar problem", report.recurring_gaps[0].verification_check)

    def test_markdown_has_only_four_sections_and_compact_appendix(self):
        service = ProfileAnalysisService()
        markdown = service.render_markdown(service.generate(report_pack()))

        self.assertIn("## Overall Summary", markdown)
        self.assertIn("## Recurring Gaps", markdown)
        self.assertIn("## Broader Related Patterns", markdown)
        self.assertIn("## Evidence Appendix", markdown)
        self.assertIn("| Test date | Test | Question |", markdown)
        self.assertIn("RG-1", markdown)
        self.assertNotIn("**Likely reasoning:**", markdown)
        self.assertNotIn("**Why it was wrong:**", markdown)
        self.assertNotIn("## Study Priorities", markdown)
        self.assertNotIn("## Teacher Intervention Notes", markdown)

    def test_appendix_maps_evidence_to_supported_finding(self):
        report = ProfileAnalysisService().generate(report_pack())

        self.assertEqual(
            {entry.evidence_id for entry in report.evidence_appendix},
            {"r1:q1", "r2:q1", "r3:q1"},
        )
        self.assertTrue(
            all(
                entry.supported_finding_ids == ["RG-1"]
                for entry in report.evidence_appendix
            )
        )

    def test_broader_pattern_is_traced_to_component_strands(self):
        pack = report_pack()
        second = capacitor_strand().model_copy(
            update={
                "strand_id": "RG-2",
                "chapter_family": "Current Electricity",
                "chapter_labels": ["Current Electricity"],
                "topics": ["Loaded voltmeter networks"],
                "title": "Circuit loading and topology",
            }
        )
        second.evidence_ids = ["r4:q1", "r5:q1"]
        second.manifestations = [
            StrandManifestation(
                evidence_id=evidence_id,
                manifestation="Assumed linear voltage without accounting for loading.",
            )
            for evidence_id in second.evidence_ids
        ]
        extra = [
            evidence(
                "r4:q1",
                "r4",
                chapter="Current Electricity",
                topic="Loaded voltmeter networks",
            ),
            evidence(
                "r5:q1",
                "r5",
                chapter="Current Electricity",
                topic="Loaded voltmeter networks",
            ),
        ]
        pack.evidence_index.update({item.evidence_id: item for item in extra})
        pack.question_count = 5
        pack.diagnosis_report_count = 5
        pack.recurring_strands.append(
            ValidatedRecurringStrand(
                strand=second,
                diagnosis_report_count=2,
                question_count=2,
            )
        )
        pack.broader_patterns = [
            BroaderConceptualPattern(
                pattern_id="BRP-1",
                title="Equations before constraints",
                shared_reasoning_gap=(
                    "Selects a familiar relation before establishing system constraints."
                ),
                common_corrective_principle=(
                    "Represent topology and constraints before selecting equations."
                ),
                component_strand_ids=["RG-1", "RG-2"],
                manifestations=[
                    BroaderPatternManifestation(
                        strand_id="RG-1",
                        chapter_family="Electrostatics and Capacitance",
                        manifestation="Does not construct capacitor node state.",
                    ),
                    BroaderPatternManifestation(
                        strand_id="RG-2",
                        chapter_family="Current Electricity",
                        manifestation="Does not construct loaded network topology.",
                    ),
                ],
                confidence="high",
                rationale="Both strands fail before equation selection.",
            )
        ]

        report = ProfileAnalysisService().generate(pack)

        self.assertEqual(
            report.broader_related_patterns[0].component_strand_ids,
            ["RG-1", "RG-2"],
        )
        self.assertIn(
            "BRP-1",
            next(
                item
                for item in report.evidence_appendix
                if item.evidence_id == "r1:q1"
            ).supported_finding_ids,
        )

    def test_empty_evidence_does_not_invent_insight(self):
        pack = LongitudinalEvidencePack(
            subject="Physics",
            diagnosis_report_count=1,
            question_count=0,
        )

        report = ProfileAnalysisService().generate(pack)

        self.assertEqual(report.recurring_gaps, [])
        self.assertIn("No conceptual strand", report.overall_summary.synthesis)

    def test_validation_rejects_unknown_appendix_finding(self):
        pack = report_pack()
        report = ProfileAnalysisService().generate(pack)
        report.evidence_appendix[0].supported_finding_ids = ["unknown"]

        with self.assertRaisesRegex(ValueError, "unknown finding"):
            validate_profile_report(report, pack)


if __name__ == "__main__":
    unittest.main()
