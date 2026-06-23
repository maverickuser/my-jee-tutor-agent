import unittest

from jee_tutor.agent.output_validation import (
    OutputValidationError,
    validate_markdown_analysis,
)


VALID_TABLE = """| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | Exact Concept Gap | What You Must Deep-Dive |
| --- | --- | --- | --- | --- | --- | --- |
| Question 6 | Electrostatics | Capacitors | Used direct formula | Missed charge sharing | Capacitor networks | Charge conservation |
| Q19 | Current Electricity | Resistance | Used linear guess | Missed temperature formula | Resistance temperature coefficient | R = R0(1 + alpha delta T) |
"""


class OutputValidationTest(unittest.TestCase):
    def test_validates_question_numbers_against_expected_images(self):
        result = validate_markdown_analysis(
            VALID_TABLE,
            expected_image_count=2,
            expected_question_numbers=["6", "19"],
        )

        self.assertEqual(result.row_count, 2)
        self.assertEqual(result.question_numbers, ["6", "19"])

    def test_rejects_generic_extra_rows(self):
        table = VALID_TABLE + (
            "| 1 | Mechanics | Kinematics | Guess | Wrong | Gap | Study |\n"
        )

        with self.assertRaisesRegex(OutputValidationError, "row count"):
            validate_markdown_analysis(
                table,
                expected_image_count=2,
                expected_question_numbers=["6", "19"],
            )

    def test_rejects_wrong_question_numbers(self):
        table = VALID_TABLE.replace("Question 6", "Question 1").replace("Q19", "Q2")

        with self.assertRaisesRegex(OutputValidationError, "question numbers"):
            validate_markdown_analysis(
                table,
                expected_image_count=2,
                expected_question_numbers=["6", "19"],
            )

    def test_rejects_missing_required_columns(self):
        table = """| Question Number | Chapter |
| --- | --- |
| 6 | Electrostatics |
"""

        with self.assertRaisesRegex(OutputValidationError, "missing required columns"):
            validate_markdown_analysis(
                table,
                expected_image_count=1,
                expected_question_numbers=["6"],
            )

    def test_data_uri_without_question_number_metadata_skips_filename_match(self):
        validate_markdown_analysis(
            VALID_TABLE.splitlines()[0]
            + "\n"
            + VALID_TABLE.splitlines()[1]
            + "\n"
            + VALID_TABLE.splitlines()[2],
            expected_image_count=1,
            expected_question_numbers=[None],
        )


if __name__ == "__main__":
    unittest.main()
