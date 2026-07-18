from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ParsedStudentS3Context(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket: str | None = None
    prefix: str = Field(min_length=1)
    student_id: str = Field(min_length=1)
    student_name: str = Field(min_length=1)
    test_name: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    questions_prefix: str = Field(min_length=1)

    @field_validator("student_id", "student_name", "test_name", "subject", "prefix", "questions_prefix")
    @classmethod
    def strip_non_blank(cls, value: str) -> str:
        value = value.strip().strip("/")
        if not value:
            raise ValueError("Profile S3 context fields must not be blank.")
        return value


class StructuredDiagnosisQuestionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str = Field(min_length=1)
    chapter: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    what_you_thought: str = Field(min_length=1)
    why_that_thought_is_wrong: str = Field(min_length=1)
    exact_concept_gap: str = Field(min_length=1)
    what_you_must_deep_dive: str = Field(min_length=1)

    @field_validator("*", mode="before")
    @classmethod
    def strip_question_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("Structured diagnosis evidence fields must not be blank.")
        return value


class StructuredDiagnosisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis_report_id: str = Field(min_length=1)
    student_id: str = Field(min_length=1)
    student_name: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    test_name: str = Field(min_length=1)
    diagnosis_date: str = Field(min_length=1)
    questions: list[StructuredDiagnosisQuestionEvidence] = Field(min_length=1)

    @field_validator("diagnosis_report_id", "student_id", "student_name", "subject", "test_name")
    @classmethod
    def strip_report_text(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("diagnosis_date")
    @classmethod
    def validate_report_date(cls, value: str) -> str:
        return _iso_datetime(value)


class StudentDiagnosisMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(min_length=1)
    email: str = Field(min_length=3)
    student_name: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    test_name: str = Field(min_length=1)
    diagnosis_report_id: str = Field(min_length=1)
    diagnosis_date: str = Field(min_length=1)
    diagnosis_json_s3_uri: str = Field(min_length=1)
    question_count: int = Field(ge=1)
    analysis_pdf_s3_uri: str | None = None
    analysis_markdown_s3_uri: str | None = None

    @field_validator("student_id", "student_name", "subject", "test_name", "diagnosis_report_id")
    @classmethod
    def strip_metadata_text(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _email(value)

    @field_validator("diagnosis_date")
    @classmethod
    def validate_metadata_date(cls, value: str) -> str:
        return _iso_datetime(value)

    @field_validator("diagnosis_json_s3_uri", "analysis_pdf_s3_uri", "analysis_markdown_s3_uri")
    @classmethod
    def validate_s3_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _non_blank(value)
        parsed = urlparse(value)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError("Expected a valid s3://bucket/key URI.")
        return value


class ProfileReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3)
    subject: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def validate_request_email(cls, value: str) -> str:
        return _email(value)

    @field_validator("subject")
    @classmethod
    def validate_request_subject(cls, value: str) -> str:
        return _non_blank(value)


def metadata_from_report(
    *,
    report: StructuredDiagnosisReport,
    email: str,
    diagnosis_json_s3_uri: str,
    analysis_pdf_s3_uri: str | None = None,
    analysis_markdown_s3_uri: str | None = None,
) -> StudentDiagnosisMetadata:
    return StudentDiagnosisMetadata(
        student_id=report.student_id,
        email=email,
        student_name=report.student_name,
        subject=report.subject,
        test_name=report.test_name,
        diagnosis_report_id=report.diagnosis_report_id,
        diagnosis_date=report.diagnosis_date,
        diagnosis_json_s3_uri=diagnosis_json_s3_uri,
        analysis_pdf_s3_uri=analysis_pdf_s3_uri,
        analysis_markdown_s3_uri=analysis_markdown_s3_uri,
        question_count=len(report.questions),
    )


def _non_blank(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Value must not be blank.")
    return value


def _email(value: str) -> str:
    value = _non_blank(value).casefold()
    if " " in value or value.count("@") != 1:
        raise ValueError("Value must be a valid email address.")
    local_part, domain = value.split("@", 1)
    if not local_part or not domain or "." not in domain:
        raise ValueError("Value must be a valid email address.")
    return value


def _iso_datetime(value: str) -> str:
    value = _non_blank(value)
    candidate = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("Value must be an ISO-8601 datetime.") from exc
    return value


def reject_sensitive_payload_keys(payload: dict[str, Any]) -> None:
    forbidden = (
        "image_data_uri",
        "base64",
        "raw_model_response",
        "raw_response",
        "stack_trace",
    )
    for key in payload:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(key).casefold())
        if any(fragment in normalized for fragment in forbidden):
            raise ValueError(f"Sensitive field is not allowed in profile data: {key}")
