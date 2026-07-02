import json
import unittest

from pydantic import ValidationError

from jee_tutor.agent.diagnosis_output import (
    DiagnosisResponse,
    QuestionDiagnosis,
    diagnosis_response_format,
    parse_and_validate_diagnosis,
    render_diagnosis_markdown,
    render_and_validate_diagnosis,
)
from jee_tutor.agent.output_validation import OutputValidationError, validate_markdown_analysis


def question(number: str = "6", **overrides):
    values = {
        "question_number": number,
        "chapter": "Electrostatics",
        "topic": "Capacitance",
        "what_you_thought": "Used $C = Q/V$",
        "why_that_thought_is_wrong": "Missed charge sharing",
        "exact_concept_gap": "Conservation of charge",
        "what_you_must_deep_dive": "Series | parallel\ncapacitors",
    }
    values.update(overrides)
    return values


class DiagnosisOutputTest(unittest.TestCase):
    def test_schema_is_strict_required_and_described(self):
        schema = diagnosis_response_format()["json_schema"]["schema"]
        item_schema = schema["$defs"]["QuestionDiagnosis"]

        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(len(item_schema["required"]), 7)
        self.assertTrue(
            all("description" in value for value in item_schema["properties"].values())
        )

    def test_strips_fields_and_rejects_missing_extra_null_non_string_and_blank(self):
        parsed = QuestionDiagnosis.model_validate(question(chapter="  Electrostatics  "))
        self.assertEqual(parsed.chapter, "Electrostatics")
        invalid = [
            {key: value for key, value in question().items() if key != "topic"},
            {**question(), "extra": "no"},
            question(topic=None),
            question(topic=123),
            question(topic="   "),
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                QuestionDiagnosis.model_validate(payload)

    def test_semantic_validation_checks_count_order_and_duplicates(self):
        for invalid in ["not-json", json.dumps({"questions": [{"topic": "x"}]})]:
            with self.subTest(invalid=invalid), self.assertRaises(OutputValidationError):
                parse_and_validate_diagnosis(invalid, expected_image_count=1)
        with self.assertRaisesRegex(OutputValidationError, "count"):
            parse_and_validate_diagnosis(
                json.dumps({"questions": [question()]}),
                expected_image_count=2,
            )
        with self.assertRaisesRegex(OutputValidationError, "image order"):
            parse_and_validate_diagnosis(
                json.dumps({"questions": [question("7"), question("6")]}),
                expected_image_count=2,
                expected_question_numbers=["6", "7"],
            )
        with self.assertRaisesRegex(OutputValidationError, "duplicate"):
            parse_and_validate_diagnosis(
                json.dumps({"questions": [question(), question()]}),
                expected_image_count=2,
            )
        with self.assertRaisesRegex(OutputValidationError, "duplicate"):
            parse_and_validate_diagnosis(
                json.dumps({"questions": [question("Unknown"), question("Unknown")]}),
                expected_image_count=2,
            )

    def test_unreadable_sentinel_can_repeat(self):
        parsed = parse_and_validate_diagnosis(
            json.dumps(
                {
                    "questions": [
                        question("Unreadable from image"),
                        question("Unreadable from image"),
                    ]
                }
            ),
            expected_image_count=2,
        )
        self.assertEqual(len(parsed.questions), 2)

    def test_renderer_escapes_structure_and_preserves_math(self):
        diagnosis = DiagnosisResponse.model_validate({"questions": [question()]})
        markdown = render_diagnosis_markdown(diagnosis)

        self.assertIn("$C = Q/V$", markdown)
        self.assertIn(r"Series \| parallel capacitors", markdown)
        self.assertEqual(len(markdown.splitlines()), 3)
        result = validate_markdown_analysis(
            markdown,
            expected_image_count=1,
            expected_question_numbers=["6"],
        )
        self.assertEqual(result.row_count, 1)
        self.assertEqual(
            render_and_validate_diagnosis(diagnosis, expected_question_numbers=["6"]),
            markdown,
        )
