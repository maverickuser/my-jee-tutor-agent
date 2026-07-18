from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jee_tutor.agent.diagnosis_output import DiagnosisResponse
from jee_tutor.profile.models import (
    ParsedStudentS3Context,
    StructuredDiagnosisQuestionEvidence,
    StructuredDiagnosisReport,
)


def build_structured_diagnosis_report(
    *,
    diagnosis: Any,
    context: ParsedStudentS3Context,
    diagnosis_report_id: str,
    diagnosis_date: str | None = None,
) -> StructuredDiagnosisReport:
    parsed = DiagnosisResponse.model_validate(diagnosis)
    return StructuredDiagnosisReport(
        diagnosis_report_id=diagnosis_report_id,
        student_id=context.student_id,
        student_name=context.student_name,
        subject=context.subject,
        test_name=context.test_name,
        diagnosis_date=diagnosis_date or datetime.now(timezone.utc).isoformat(),
        questions=[
            StructuredDiagnosisQuestionEvidence.model_validate(question.model_dump())
            for question in parsed.questions
        ],
    )
