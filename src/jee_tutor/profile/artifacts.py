"""PDF persistence for student-facing profile reports."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
from typing import Protocol
from urllib.parse import urlparse

import boto3

from jee_tutor.artifacts.pdf import PandocPdfRenderer

logger = logging.getLogger(__name__)
DEFAULT_PROFILE_REPORT_S3_PREFIX = "profile-reports"
DEFAULT_PROFILE_REPORT_S3_BUCKET = "jee-tutor-agent-terraform-state"


class PdfRenderer(Protocol):
    def render(self, markdown: str) -> bytes: ...


class S3ObjectWriter(Protocol):
    def put_object(self, **kwargs): ...


@dataclass(frozen=True)
class ProfileReportArtifactConfig:
    bucket: str = DEFAULT_PROFILE_REPORT_S3_BUCKET
    prefix: str = DEFAULT_PROFILE_REPORT_S3_PREFIX
    region: str = "ap-south-1"

    @classmethod
    def from_environment(cls) -> "ProfileReportArtifactConfig":
        return cls(
            bucket=os.getenv(
                "PROFILE_REPORT_S3_BUCKET", DEFAULT_PROFILE_REPORT_S3_BUCKET
            ).strip(),
            prefix=os.getenv(
                "PROFILE_REPORT_S3_PREFIX",
                DEFAULT_PROFILE_REPORT_S3_PREFIX,
            ).strip("/"),
            region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-south-1",
        )


@dataclass(frozen=True)
class ProfileReportArtifactResult:
    pdf_uri: str | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        if not self.pdf_uri and not self.error:
            return "disabled"
        if self.pdf_uri:
            return "succeeded"
        return "failed"

    @property
    def errors(self) -> list[str]:
        return [self.error] if self.error else []


class ProfileReportArtifactWriter:
    def __init__(
        self,
        *,
        config: ProfileReportArtifactConfig | None = None,
        s3_client: S3ObjectWriter | None = None,
        pdf_renderer: PdfRenderer | None = None,
    ):
        self.config = config or ProfileReportArtifactConfig.from_environment()
        self.s3_client = s3_client
        self.pdf_renderer = pdf_renderer or PandocPdfRenderer()

    def write(
        self,
        *,
        student_id: str,
        student_name: str,
        subject: str,
        profile_markdown: str,
    ) -> ProfileReportArtifactResult:
        if not self.config.bucket:
            return ProfileReportArtifactResult()

        pdf_uri = self._profile_uri(
            student_id=student_id,
            student_name=student_name,
            subject=subject,
            suffix=".pdf",
        )
        try:
            pdf_bytes = self.pdf_renderer.render(profile_markdown)
            self._upload(pdf_uri, pdf_bytes, "application/pdf")
            logger.info("profile_report_pdf_upload uri=%s bytes=%s", pdf_uri, len(pdf_bytes))
            return ProfileReportArtifactResult(pdf_uri=pdf_uri)
        except Exception as exc:
            error = _artifact_error("PDF", exc)
            logger.exception(
                "profile_report_pdf_error error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )
            return ProfileReportArtifactResult(error=error)

    def _profile_uri(
        self,
        *,
        student_id: str,
        student_name: str,
        subject: str,
        suffix: str,
    ) -> str:
        key_parts = [
            part
            for part in [
                self.config.prefix,
                f"{_safe_path_part(student_name)}+{_safe_path_part(student_id)}",
                _safe_path_part(subject),
                f"{_safe_path_part(subject)}_profile_report{suffix}",
            ]
            if part
        ]
        return f"s3://{self.config.bucket}/{'/'.join(key_parts)}"

    def _upload(self, s3_uri: str, body: bytes, content_type: str) -> None:
        bucket, key = _parse_s3_uri(s3_uri)
        self._s3().put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def _s3(self):
        if self.s3_client is None:
            self.s3_client = boto3.client("s3", region_name=self.config.region)
        return self.s3_client


def _safe_path_part(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    if not normalized:
        raise ValueError("Profile path component is blank after sanitization.")
    return normalized


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _artifact_error(artifact: str, exc: Exception) -> str:
    message = str(exc) or "[no message]"
    return f"Failed to write profile report {artifact}: {exc.__class__.__name__}: {message}"


__all__ = [
    "ProfileReportArtifactConfig",
    "ProfileReportArtifactResult",
    "ProfileReportArtifactWriter",
]
