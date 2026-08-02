import io
import json
import unittest

from jee_tutor.profile.actionable import ActionableInsightService, ImportantChapter
from jee_tutor.profile.evidence import ProfileEvidenceItem
from jee_tutor.profile.hierarchical import (
    ConceptualStrand,
    ConceptualStrandOutput,
    StrandManifestation,
)
from jee_tutor.profile.weightage import ChapterWeightageService


def evidence(report_id: str, number: str, *, gap: str = "Checked only one case"):
    return ProfileEvidenceItem(
        evidence_id=f"{report_id}:q1",
        evidence_reference=f"2026-01-01 : Test : Q{number}",
        diagnosis_report_id=report_id,
        diagnosis_json_s3_uri=f"s3://diagnoses/{report_id}.json",
        subject="Maths",
        test_name="Test",
        diagnosis_date="2026-01-01T00:00:00Z",
        question_number=number,
        chapter="Functions",
        topic="Piecewise functions",
        exact_concept_gap=gap,
        likely_thought="You checked only one branch.",
        why_wrong="Every case must be checked.",
        deep_dive_recommendation="Solve all branches.",
    )


class ActionableProfileTest(unittest.TestCase):
    def test_recurring_pattern_becomes_plain_student_action_with_internal_evidence(self):
        items = [evidence("r1", "1"), evidence("r2", "2")]
        strand = ConceptualStrand(
            strand_id="all-cases",
            chapter_family="Functions",
            chapter_labels=["Functions"],
            topics=["Piecewise functions"],
            title="Incomplete solution-space coverage",
            missing_mental_model="All branches form the solution",
            shared_failure="Checks one branch only",
            corrective_model="Check every branch and combine the valid answers",
            evidence_ids=[item.evidence_id for item in items],
            manifestations=[
                StrandManifestation(evidence_id=item.evidence_id, manifestation="Missed a branch")
                for item in items
            ],
            confidence="high",
            rationale="Same behavior and prevention.",
        )
        report = ActionableInsightService().generate(
            subject="Maths",
            evidence_items=items,
            strand_output=ConceptualStrandOutput(strands=[strand]),
        )
        markdown = ActionableInsightService.render_markdown(report)

        self.assertEqual(len(report.insights), 1)
        self.assertEqual(report.insights[0].heading, "Have I checked every possible case?")
        self.assertIn("List the cases first", report.insights[0].do)
        self.assertIn("piecewise", report.insights[0].ask_this_when_you_see.casefold())
        self.assertEqual(len(report.internal_evidence[0].supporting_questions), 2)
        self.assertEqual(
            report.internal_evidence[0].supporting_questions[0].reasoning_provenance,
            "inferred_from_diagnosis",
        )
        self.assertEqual(report.internal_evidence[0].likely_mark_impact, 2)
        self.assertNotIn("r1:q1", markdown)
        self.assertNotIn("confidence", markdown.casefold())
        self.assertNotIn("inferred", markdown.casefold())

    def test_single_question_is_not_called_recurring(self):
        item = evidence("r1", "1")
        report = ActionableInsightService().generate(
            subject="Maths",
            evidence_items=[item],
            strand_output=ConceptualStrandOutput(),
        )
        self.assertEqual(report.insights, [])
        self.assertEqual([x.evidence_id for x in report.question_level_feedback], ["r1:q1"])

    def test_all_failure_types_have_specific_headings_actions_and_triggers(self):
        cases = [
            ("calculation error", "execution", "calculation"),
            ("misread the unit", "attention", "detail"),
            ("wrong diagram strategy", "strategy_representation", "diagram"),
            ("missed one case", "concept_applied_incompletely", "every possible case"),
            ("formula applied incorrectly", "concept_applied_incorrectly", "right way"),
            ("required theorem was absent", "concept_not_applied", "rule"),
        ]
        service = ActionableInsightService()
        for index, (gap, expected_type, heading_fragment) in enumerate(cases):
            items = [
                evidence(f"r{index}-a", "1", gap=gap),
                evidence(f"r{index}-b", "2", gap=gap),
            ]
            for item in items:
                item.likely_thought = gap
                item.why_wrong = gap
            strand = recurring_strand(f"strand-{index}", items)
            report = service.generate(
                subject="Chemistry" if index == 1 else "Physics",
                evidence_items=items,
                strand_output=ConceptualStrandOutput(strands=[strand]),
            )
            self.assertEqual(
                report.internal_evidence[0].supporting_questions[0].failure_type,
                expected_type,
            )
            self.assertIn(heading_fragment, report.insights[0].heading.casefold())
            self.assertTrue(report.insights[0].do.endswith("."))
            self.assertTrue(report.insights[0].ask_this_when_you_see.endswith("."))

    def test_report_limits_insights_to_three_and_renders_weightage(self):
        items = []
        strands = []
        for index in range(4):
            pair = [
                evidence(f"r{index}-a", "1"),
                evidence(f"r{index}-b", "2"),
            ]
            items.extend(pair)
            strands.append(recurring_strand(f"strand-{index}", pair))
        report = ActionableInsightService().generate(
            subject="Maths",
            evidence_items=items,
            strand_output=ConceptualStrandOutput(strands=strands),
            important_chapters=[
                ImportantChapter(
                    chapter="Functions",
                    mistake_count=4,
                    combined_weightage_percent=6.53,
                )
            ],
        )
        markdown = ActionableInsightService.render_markdown(report)
        self.assertEqual(len(report.insights), 3)
        self.assertIn("## Chapters to fix first", markdown)
        self.assertIn("6.53% JEE weightage", markdown)
        self.assertEqual(len(report.question_level_feedback), 2)

    def test_no_pattern_markdown_gives_question_level_direction(self):
        report = ActionableInsightService().generate(
            subject="Maths",
            evidence_items=[evidence("r1", "1")],
            strand_output=ConceptualStrandOutput(),
        )
        markdown = ActionableInsightService.render_markdown(report)
        self.assertIn("No mistake pattern has repeated enough yet", markdown)
        self.assertIn("correct each diagnosed question separately", markdown)

    def test_weightage_lists_only_repeated_chapters_in_weight_order(self):
        payload = {
            "chapters": [
                {"chapter": "Functions", "combined_weightage_percent": 6.5},
                {"chapter": "Probability", "combined_weightage_percent": 7.3},
            ]
        }
        s3 = FakeS3(payload)
        priorities = ChapterWeightageService(s3_client=s3).priorities(
            subject="Maths",
            evidence_items=[evidence("r1", "1"), evidence("r2", "2")],
        )
        self.assertEqual([item.chapter for item in priorities], ["Functions"])
        self.assertEqual(s3.calls, 1)


class FakeS3:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get_object(self, **_kwargs):
        self.calls += 1
        return {"Body": io.BytesIO(json.dumps(self.payload).encode())}


def recurring_strand(strand_id, items):
    return ConceptualStrand(
        strand_id=strand_id,
        chapter_family="Functions",
        chapter_labels=["Functions"],
        topics=["Piecewise functions"],
        title="Shared failure",
        missing_mental_model="Required model",
        shared_failure="Same observable behavior",
        corrective_model="One corrective model",
        evidence_ids=[item.evidence_id for item in items],
        manifestations=[
            StrandManifestation(
                evidence_id=item.evidence_id,
                manifestation="Same visible error",
            )
            for item in items
        ],
        confidence="high",
        rationale="One action prevents both errors.",
    )


if __name__ == "__main__":
    unittest.main()
