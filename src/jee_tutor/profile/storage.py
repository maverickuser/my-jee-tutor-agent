from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Protocol
from urllib.parse import urlparse

import boto3

from jee_tutor.profile.models import StudentDiagnosisMetadata, StructuredDiagnosisReport


class StudentDiagnosisMetadataStore(Protocol):
    def put_metadata(self, metadata: StudentDiagnosisMetadata) -> None: ...

    def query_by_email_subject(self, *, email: str, subject: str) -> list[StudentDiagnosisMetadata]: ...


class StructuredDiagnosisArtifactStore(Protocol):
    def write_report(self, *, s3_uri: str, report: StructuredDiagnosisReport) -> None: ...

    def load_report(self, *, s3_uri: str) -> StructuredDiagnosisReport: ...


class NullStudentDiagnosisMetadataStore:
    def put_metadata(self, metadata: StudentDiagnosisMetadata) -> None:
        return None

    def query_by_email_subject(self, *, email: str, subject: str) -> list[StudentDiagnosisMetadata]:
        return []


class InMemoryStudentDiagnosisMetadataStore:
    def __init__(self):
        self.records: list[StudentDiagnosisMetadata] = []

    def put_metadata(self, metadata: StudentDiagnosisMetadata) -> None:
        self.records.append(metadata)

    def query_by_email_subject(self, *, email: str, subject: str) -> list[StudentDiagnosisMetadata]:
        normalized_email = email.strip().casefold()
        normalized_subject = subject.strip().casefold()
        return [
            record
            for record in self.records
            if record.email == normalized_email and record.subject.casefold() == normalized_subject
        ]


class InMemoryStructuredDiagnosisArtifactStore:
    def __init__(self):
        self.reports: dict[str, StructuredDiagnosisReport] = {}

    def write_report(self, *, s3_uri: str, report: StructuredDiagnosisReport) -> None:
        self.reports[s3_uri] = report

    def load_report(self, *, s3_uri: str) -> StructuredDiagnosisReport:
        return self.reports[s3_uri]


@dataclass(frozen=True)
class StudentDiagnosisMetadataConfig:
    table_name: str = ""
    region: str = "ap-south-1"
    enabled: bool = False

    @classmethod
    def from_environment(cls) -> "StudentDiagnosisMetadataConfig":
        table_name = os.getenv("STUDENT_DIAGNOSIS_METADATA_TABLE_NAME", "").strip()
        enabled_value = os.getenv("STUDENT_DIAGNOSIS_METADATA_ENABLED", "true").strip().lower()
        enabled = enabled_value in {"1", "true", "yes", "on"} and bool(table_name)
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-south-1"
        return cls(table_name=table_name, region=region, enabled=enabled)


class DynamoDbStudentDiagnosisMetadataStore:
    def __init__(self, *, table_name: str, region: str):
        self.table_name = table_name
        self.region = region
        self._table = None

    @classmethod
    def from_environment(cls) -> StudentDiagnosisMetadataStore:
        config = StudentDiagnosisMetadataConfig.from_environment()
        if not config.enabled:
            return NullStudentDiagnosisMetadataStore()
        return cls(table_name=config.table_name, region=config.region)

    def put_metadata(self, metadata: StudentDiagnosisMetadata) -> None:
        self._table_client().put_item(Item=_metadata_item(metadata))

    def query_by_email_subject(self, *, email: str, subject: str) -> list[StudentDiagnosisMetadata]:
        response = self._table_client().query(
            KeyConditionExpression="email = :email AND begins_with(subject_report_key, :subject_prefix)",
            ExpressionAttributeValues={
                ":email": email.strip().casefold(),
                ":subject_prefix": f"{subject.strip().casefold()}#",
            },
        )
        return [
            StudentDiagnosisMetadata.model_validate(_metadata_model_item(item))
            for item in response.get("Items", [])
        ]

    def _table_client(self):
        if self._table is None:
            self._table = boto3.resource("dynamodb", region_name=self.region).Table(
                self.table_name
            )
        return self._table


def build_student_diagnosis_metadata_store() -> StudentDiagnosisMetadataStore:
    return DynamoDbStudentDiagnosisMetadataStore.from_environment()


@dataclass(frozen=True)
class StructuredDiagnosisArtifactConfig:
    region: str = "ap-south-1"

    @classmethod
    def from_environment(cls) -> "StructuredDiagnosisArtifactConfig":
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-south-1"
        return cls(region=region)


class S3StructuredDiagnosisArtifactStore:
    def __init__(self, *, region: str, s3_client=None):
        self.region = region
        self.s3_client = s3_client

    @classmethod
    def from_environment(cls) -> "S3StructuredDiagnosisArtifactStore":
        config = StructuredDiagnosisArtifactConfig.from_environment()
        return cls(region=config.region)

    def write_report(self, *, s3_uri: str, report: StructuredDiagnosisReport) -> None:
        bucket, key = _parse_s3_uri(s3_uri)
        self._s3().put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(report.model_dump(mode="json"), sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )

    def load_report(self, *, s3_uri: str) -> StructuredDiagnosisReport:
        bucket, key = _parse_s3_uri(s3_uri)
        payload = self._s3().get_object(Bucket=bucket, Key=key)["Body"].read()
        return StructuredDiagnosisReport.model_validate_json(payload)

    def _s3(self):
        if self.s3_client is None:
            self.s3_client = boto3.client("s3", region_name=self.region)
        return self.s3_client


def build_structured_diagnosis_artifact_store() -> StructuredDiagnosisArtifactStore:
    return S3StructuredDiagnosisArtifactStore.from_environment()


def _metadata_item(metadata: StudentDiagnosisMetadata) -> dict[str, object]:
    item = metadata.model_dump(exclude_none=True)
    item["subject_report_key"] = (
        f"{metadata.subject.casefold()}#{metadata.diagnosis_date}#{metadata.diagnosis_report_id}"
    )
    return item


def _metadata_model_item(item: dict[str, object]) -> dict[str, object]:
    model_item = dict(item)
    model_item.pop("subject_report_key", None)
    return model_item


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")
