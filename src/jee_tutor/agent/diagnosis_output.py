from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from jee_tutor.agent.output_validation import (
    OutputValidationError,
    REQUIRED_MARKDOWN_COLUMNS,
    validate_markdown_analysis,
)


DIAGNOSIS_SCHEMA_NAME = "jee_question_diagnosis"
DIAGNOSIS_SCHEMA_VERSION = 1
UNREADABLE_SENTINEL = "Unreadable from image"
UNABLE_TO_DETERMINE_SENTINEL = "Unable to determine from image"


class QuestionDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str = Field(
        min_length=1,
        description="Question number visible in the image, or 'Unreadable from image'.",
    )
    chapter: str = Field(
        min_length=1,
        description="JEE chapter supported by the image, or 'Unable to determine from image'.",
    )
    topic: str = Field(
        min_length=1,
        description="Specific topic tested, or 'Unable to determine from image'.",
    )
    what_you_thought: str = Field(
        min_length=1,
        description="Likely student reasoning grounded in visible attempt evidence.",
    )
    why_that_thought_is_wrong: str = Field(
        min_length=1,
        description="Why the visible or likely reasoning is wrong or incomplete.",
    )
    exact_concept_gap: str = Field(
        min_length=1,
        description="The precise concept or reasoning gap evidenced by the attempt.",
    )
    what_you_must_deep_dive: str = Field(
        min_length=1,
        description="Specific concepts or techniques the student should study next.",
    )

    @field_validator("*", mode="before")
    @classmethod
    def strip_and_reject_blank_strings(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("Diagnosis fields must not be blank.")
        return value


class DiagnosisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[QuestionDiagnosis] = Field(
        min_length=1,
        description="One diagnosis per invocation image, in the original image order.",
    )


def diagnosis_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": DIAGNOSIS_SCHEMA_NAME,
            "strict": True,
            "schema": DiagnosisResponse.model_json_schema(),
        },
    }


def parse_and_validate_diagnosis(
    content: str,
    *,
    expected_image_count: int,
    expected_question_numbers: list[str | None] | None = None,
) -> DiagnosisResponse:
    try:
        decoded = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise OutputValidationError(
            "Structured diagnosis output is not valid JSON.",
            ["Validation category: structured_output_invalid_json."],
        ) from exc

    try:
        diagnosis = DiagnosisResponse.model_validate(decoded)
    except ValidationError as exc:
        categories = sorted({".".join(str(part) for part in error["loc"]) for error in exc.errors()})
        raise OutputValidationError(
            "Structured diagnosis output does not match the required schema.",
            [
                "Validation category: structured_output_schema_mismatch.",
                f"Invalid field count: {len(categories)}.",
            ],
        ) from exc

    if len(diagnosis.questions) != expected_image_count:
        raise OutputValidationError(
            "Structured diagnosis question count does not match resolved image count.",
            [
                "Validation category: structured_output_wrong_question_count.",
                f"Expected image count: {expected_image_count}.",
                f"Actual question count: {len(diagnosis.questions)}.",
            ],
        )

    actual_numbers = [question.question_number for question in diagnosis.questions]
    normalized_actual = [_normalize_question_number(value) for value in actual_numbers]
    duplicate_keys = [
        None
        if value.strip().casefold() == UNREADABLE_SENTINEL.casefold()
        else (_normalize_question_number(value) or value.strip().casefold())
        for value in actual_numbers
    ]
    duplicate_numbers = {
        number
        for number in duplicate_keys
        if number is not None and duplicate_keys.count(number) > 1
    }
    if duplicate_numbers:
        raise OutputValidationError(
            "Structured diagnosis contains duplicate question numbers.",
            [
                "Validation category: structured_output_duplicate_question.",
                f"Duplicate question count: {len(duplicate_numbers)}.",
            ],
        )

    expected = expected_question_numbers or []
    if expected and all(number is not None for number in expected):
        normalized_expected = [_normalize_question_number(number or "") for number in expected]
        if normalized_actual != normalized_expected:
            raise OutputValidationError(
                "Structured diagnosis question numbers do not match image order.",
                [
                    "Validation category: structured_output_question_number_mismatch.",
                    f"Expected question count: {len(normalized_expected)}.",
                    f"Actual question count: {len(normalized_actual)}.",
                ],
            )

    return diagnosis


def render_diagnosis_markdown(diagnosis: DiagnosisResponse) -> str:
    field_names = (
        "question_number",
        "chapter",
        "topic",
        "what_you_thought",
        "why_that_thought_is_wrong",
        "exact_concept_gap",
        "what_you_must_deep_dive",
    )
    lines = [
        "| " + " | ".join(REQUIRED_MARKDOWN_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in REQUIRED_MARKDOWN_COLUMNS) + " |",
    ]
    for question in diagnosis.questions:
        cells = [_escape_markdown_cell(getattr(question, field)) for field in field_names]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_and_validate_diagnosis(
    diagnosis: DiagnosisResponse,
    *,
    expected_question_numbers: list[str | None] | None = None,
) -> str:
    markdown = render_diagnosis_markdown(diagnosis)
    validate_markdown_analysis(
        markdown,
        expected_image_count=len(diagnosis.questions),
        expected_question_numbers=expected_question_numbers
        or [None] * len(diagnosis.questions),
    )
    return markdown


def _escape_markdown_cell(value: str) -> str:
    normalized = re.sub(r"\s*\r?\n\s*", " ", value.strip())
    return normalized.replace("\\", "\\\\").replace("|", "\\|")


def _normalize_question_number(value: str) -> str | None:
    if value.strip().casefold() == UNREADABLE_SENTINEL.casefold():
        return None
    matches = re.findall(r"\d+", value)
    return str(int(matches[-1])) if matches else None
