from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jee_tutor.profile.models import (
    ProfileReportRequest,
    StudentDiagnosisMetadata,
    StructuredDiagnosisReport,
)
from jee_tutor.profile.storage import (
    StructuredDiagnosisArtifactStore,
    StudentDiagnosisMetadataStore,
)


class ProfileEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    evidence_reference: str = Field(min_length=1)
    diagnosis_report_id: str = Field(min_length=1)
    diagnosis_json_s3_uri: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    test_name: str = Field(min_length=1)
    test_date: str | None = None
    test_date_source: str = "unavailable"
    diagnosis_date: str = Field(min_length=1)
    question_number: str = Field(min_length=1)
    chapter: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    canonical_chapter: str | None = None
    canonical_topic: str | None = None
    exact_concept_gap: str = Field(min_length=1)
    likely_thought: str = Field(min_length=1)
    why_wrong: str = Field(min_length=1)
    deep_dive_recommendation: str = Field(min_length=1)

    @model_validator(mode="after")
    def default_canonical_location(self):
        self.canonical_chapter = self.canonical_chapter or _canonical_label(self.chapter)
        self.canonical_topic = self.canonical_topic or _canonical_label(self.topic)
        return self


class ProfileEvidenceLoadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: ProfileReportRequest
    metadata_records: list[StudentDiagnosisMetadata] = Field(default_factory=list)
    reports: list[StructuredDiagnosisReport] = Field(default_factory=list)
    evidence_items: list[ProfileEvidenceItem] = Field(default_factory=list)
    no_history: bool = False
    message: str | None = None
    loading_errors: list[str] = Field(default_factory=list)


class ProfileEvidenceLoader:
    def __init__(
        self,
        *,
        metadata_store: StudentDiagnosisMetadataStore,
        artifact_store: StructuredDiagnosisArtifactStore,
    ):
        self.metadata_store = metadata_store
        self.artifact_store = artifact_store

    def load(self, request: ProfileReportRequest) -> ProfileEvidenceLoadResult:
        metadata_records = self.metadata_store.query_by_email_subject(
            email=request.email,
            subject=request.subject,
        )
        if not metadata_records:
            return ProfileEvidenceLoadResult(
                request=request,
                no_history=True,
                message="No diagnosis history is available for this student and subject.",
            )

        reports: list[StructuredDiagnosisReport] = []
        loading_errors: list[str] = []
        for metadata in metadata_records:
            try:
                reports.append(
                    self.artifact_store.load_report(
                        s3_uri=metadata.diagnosis_json_s3_uri
                    )
                )
            except Exception as exc:
                loading_errors.append(
                    f"{metadata.diagnosis_report_id}: {exc.__class__.__name__}"
                )
        evidence_items = _evidence_items_from_reports(metadata_records, reports)
        if not evidence_items:
            return ProfileEvidenceLoadResult(
                request=request,
                metadata_records=metadata_records,
                reports=reports,
                loading_errors=loading_errors,
                no_history=True,
                message="No diagnosis question evidence is available for this student and subject.",
            )
        return ProfileEvidenceLoadResult(
            request=request,
            metadata_records=metadata_records,
            reports=reports,
            evidence_items=evidence_items,
            loading_errors=loading_errors,
        )


def _evidence_items_from_reports(
    metadata_records: list[StudentDiagnosisMetadata],
    reports: list[StructuredDiagnosisReport],
) -> list[ProfileEvidenceItem]:
    reports_by_id = {report.diagnosis_report_id: report for report in reports}
    evidence_items: list[ProfileEvidenceItem] = []
    for metadata in metadata_records:
        report = reports_by_id.get(metadata.diagnosis_report_id)
        if report is None:
            continue
        if len(report.questions) != metadata.question_count:
            raise ValueError(
                "Structured diagnosis report question count does not match metadata."
            )
        for index, question in enumerate(report.questions, start=1):
            evidence_items.append(
                ProfileEvidenceItem(
                    evidence_id=f"{report.diagnosis_report_id}:q{index}",
                    evidence_reference=_evidence_reference(
                        test_date=metadata.test_date,
                        test_name=metadata.test_name,
                        question_number=question.question_number,
                    ),
                    diagnosis_report_id=report.diagnosis_report_id,
                    diagnosis_json_s3_uri=metadata.diagnosis_json_s3_uri,
                    subject=report.subject,
                    test_name=metadata.test_name,
                    test_date=metadata.test_date,
                    test_date_source="assessment_metadata"
                    if metadata.test_date
                    else "unavailable",
                    diagnosis_date=metadata.diagnosis_date,
                    question_number=question.question_number,
                    chapter=question.chapter,
                    topic=question.topic,
                    canonical_chapter=_canonical_label(question.chapter),
                    canonical_topic=_canonical_label(question.topic),
                    exact_concept_gap=question.exact_concept_gap,
                    likely_thought=question.what_you_thought,
                    why_wrong=question.why_that_thought_is_wrong,
                    deep_dive_recommendation=question.what_you_must_deep_dive,
                )
            )
    return evidence_items


def _evidence_reference(
    *,
    test_date: str | None,
    test_name: str,
    question_number: str,
) -> str:
    date_label = test_date or "test-date-unavailable"
    question_label = question_number.strip()
    if not question_label.casefold().startswith("q"):
        question_label = f"Q{question_label}"
    return f"{date_label} : {test_name} : {question_label}"


def _canonical_label(value: str) -> str:
    return " ".join(value.strip().split())
