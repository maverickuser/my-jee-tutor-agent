"""Application orchestration for actionable student profile reports."""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import ValidationError

from jee_tutor.profile.artifacts import ProfileReportArtifactWriter
from jee_tutor.profile.actionable import ActionableInsightService
from jee_tutor.profile.evidence import ProfileEvidenceLoader
from jee_tutor.profile.models import ProfileReportRequest
from jee_tutor.profile.weightage import ChapterWeightageService
from jee_tutor.profile.hierarchical import ConceptualStrandAnalyzer
from jee_tutor.agent.observability import LangfuseObservability
from jee_tutor.profile.storage import (
    StructuredDiagnosisArtifactStore,
    StudentDiagnosisMetadataStore,
    build_structured_diagnosis_artifact_store,
    build_student_diagnosis_metadata_store,
)

logger = logging.getLogger(__name__)


class StudentProfileApplicationService:
    def __init__(
        self,
        *,
        metadata_store: StudentDiagnosisMetadataStore | None = None,
        artifact_store: StructuredDiagnosisArtifactStore | None = None,
        conceptual_strand_analyzer: ConceptualStrandAnalyzer | None = None,
        actionable_service: ActionableInsightService | None = None,
        weightage_service: ChapterWeightageService | None = None,
        artifact_writer: ProfileReportArtifactWriter | None = None,
        observability: LangfuseObservability | None = None,
    ):
        self.metadata_store = metadata_store or build_student_diagnosis_metadata_store()
        self.artifact_store = artifact_store or build_structured_diagnosis_artifact_store()
        self.conceptual_strand_analyzer = (
            conceptual_strand_analyzer or ConceptualStrandAnalyzer()
        )
        self.actionable_service = actionable_service or ActionableInsightService()
        self.weightage_service = weightage_service or ChapterWeightageService()
        self.artifact_writer = artifact_writer or ProfileReportArtifactWriter()
        self.observability = observability or LangfuseObservability()

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        safe_input = {
            "task": "profile",
            "subject": payload.get("subject"),
            "has_student_identity": bool(payload.get("email") or payload.get("recipient_email")),
        }
        with self.observability.invocation_span(
            input_payload=safe_input,
            tags=["profile", "actionable-insights"],
            metadata={"task": "profile"},
        ) as span:
            result = self._handle(payload)
            if span:
                span.update(
                    output={
                        "profile_status": result.get("profile_status"),
                        "subject": result.get("subject"),
                        "artifact_status": result.get("profile_artifact_status"),
                    }
                )
            return result

    def _handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        runtime_commit_sha = _runtime_commit_sha()
        try:
            request = ProfileReportRequest.model_validate(
                {
                    "email": payload.get("email") or payload.get("recipient_email"),
                    "subject": payload.get("subject"),
                }
            )
        except ValidationError as exc:
            return _invalid_request_response(exc, runtime_commit_sha)

        evidence_result = ProfileEvidenceLoader(
            metadata_store=self.metadata_store,
            artifact_store=self.artifact_store,
        ).load(request)
        if evidence_result.no_history:
            return _no_history_response(
                subject=request.subject,
                message=evidence_result.message,
                runtime_commit_sha=runtime_commit_sha,
            )

        strand_output = self.conceptual_strand_analyzer.analyze(
            evidence_result.evidence_items,
            subject=request.subject,
        )
        report = self.actionable_service.generate(
            subject=request.subject,
            evidence_items=evidence_result.evidence_items,
            strand_output=strand_output,
            important_chapters=self.weightage_service.priorities(
                subject=request.subject,
                evidence_items=evidence_result.evidence_items,
            ),
        )
        profile_markdown = self.actionable_service.render_markdown(report)
        profile_markdown = (
            f"Student: {evidence_result.reports[0].student_name}\n\n"
            f"{profile_markdown}"
        )
        try:
            artifact_result = self.artifact_writer.write(
                student_id=evidence_result.reports[0].student_id,
                student_name=evidence_result.reports[0].student_name,
                subject=request.subject,
                profile_markdown=profile_markdown,
            )
        except Exception as exc:
            logger.exception(
                "profile_artifact_unhandled_error subject=%s error_type=%s",
                request.subject,
                exc.__class__.__name__,
            )
            return _artifact_failure_response(
                subject=request.subject,
                status="failed",
                errors=[exc.__class__.__name__],
                runtime_commit_sha=runtime_commit_sha,
            )
        if artifact_result.status != "succeeded" or not artifact_result.pdf_uri:
            return _artifact_failure_response(
                subject=request.subject,
                status=artifact_result.status,
                errors=artifact_result.errors,
                runtime_commit_sha=runtime_commit_sha,
            )
        student_report = report.model_dump(
            exclude={"internal_evidence", "question_level_feedback"}
        )
        return {
            "profile_status": "succeeded",
            "subject": request.subject,
            "profile_report": student_report,
            "profile_internal_metadata": {
                "insights": [item.model_dump() for item in report.internal_evidence],
                "question_level_feedback": [
                    item.model_dump() for item in report.question_level_feedback
                ],
                "evidence_loading_errors": evidence_result.loading_errors,
            },
            "profile_markdown": profile_markdown,
            "profile_artifact_status": artifact_result.status,
            "profile_report_pdf_uri": artifact_result.pdf_uri,
            "profile_artifact_errors": artifact_result.errors,
            "runtime_commit_sha": runtime_commit_sha,
        }


def _runtime_commit_sha() -> str | None:
    value = os.getenv("JEE_TUTOR_GIT_SHA", "").strip()
    return value if value and value != "unknown" else None


def _invalid_request_response(
    exc: ValidationError, runtime_commit_sha: str | None
) -> dict[str, Any]:
    return {
        "profile_status": "invalid_request",
        "error": "Invalid student profile request.",
        "details": [error["msg"] for error in exc.errors()],
        "runtime_commit_sha": runtime_commit_sha,
    }


def _no_history_response(
    *, subject: str, message: str | None, runtime_commit_sha: str | None
) -> dict[str, Any]:
    return {
        "profile_status": "no_history",
        "message": message,
        "subject": subject,
        "runtime_commit_sha": runtime_commit_sha,
    }


def _artifact_failure_response(
    *,
    subject: str,
    status: str,
    errors: list[str],
    runtime_commit_sha: str | None,
) -> dict[str, Any]:
    return {
        "profile_status": "artifact_failed",
        "error": "The profile PDF could not be created.",
        "subject": subject,
        "profile_artifact_status": status,
        "profile_artifact_errors": errors,
        "runtime_commit_sha": runtime_commit_sha,
    }


__all__ = ["StudentProfileApplicationService"]
