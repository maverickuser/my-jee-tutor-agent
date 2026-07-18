from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jee_tutor.profile.evidence import ProfileEvidenceLoader
from jee_tutor.profile.models import ProfileReportRequest
from jee_tutor.profile.reporting import (
    ProfileAnalysisService,
    build_profile_analysis_service_from_environment,
    validate_profile_report,
)
from jee_tutor.profile.semantic import (
    SemanticGapAnalyzer,
    build_longitudinal_evidence_pack,
)
from jee_tutor.profile.storage import (
    StructuredDiagnosisArtifactStore,
    StudentDiagnosisMetadataStore,
    build_structured_diagnosis_artifact_store,
    build_student_diagnosis_metadata_store,
)

class StudentProfileApplicationService:
    def __init__(
        self,
        *,
        metadata_store: StudentDiagnosisMetadataStore | None = None,
        artifact_store: StructuredDiagnosisArtifactStore | None = None,
        semantic_analyzer: SemanticGapAnalyzer | None = None,
        report_service: ProfileAnalysisService | None = None,
    ):
        self.metadata_store = metadata_store or build_student_diagnosis_metadata_store()
        self.artifact_store = artifact_store or build_structured_diagnosis_artifact_store()
        self.semantic_analyzer = semantic_analyzer or SemanticGapAnalyzer()
        self.report_service = report_service or build_profile_analysis_service_from_environment()

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = ProfileReportRequest.model_validate(
                {
                    "email": payload.get("email") or payload.get("recipient_email"),
                    "subject": payload.get("subject"),
                }
            )
        except ValidationError as exc:
            return {
                "profile_status": "invalid_request",
                "error": "Invalid student profile request.",
                "details": [error["msg"] for error in exc.errors()],
            }

        evidence_result = ProfileEvidenceLoader(
            metadata_store=self.metadata_store,
            artifact_store=self.artifact_store,
        ).load(request)
        if evidence_result.no_history:
            return {
                "profile_status": "no_history",
                "message": evidence_result.message,
                "subject": request.subject,
            }

        clusters = self.semantic_analyzer.cluster(
            evidence_result.evidence_items,
            subject=request.subject,
        )
        evidence_pack = build_longitudinal_evidence_pack(
            subject=request.subject,
            evidence_items=evidence_result.evidence_items,
            clusters=clusters,
        )
        report = self.report_service.generate(evidence_pack)
        validate_profile_report(report, evidence_pack)
        return {
            "profile_status": "succeeded",
            "subject": request.subject,
            "profile_report": report.model_dump(),
            "profile_markdown": self.report_service.render_markdown(report),
        }


__all__ = ["StudentProfileApplicationService"]
