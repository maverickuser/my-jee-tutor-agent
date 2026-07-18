from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
import re
from urllib.parse import urlparse

import boto3

from jee_tutor.artifacts.pdf import PandocPdfRenderer
from jee_tutor.profile.reporting import ProfileReportOutput


logger = logging.getLogger(__name__)
DEFAULT_PROFILE_REPORT_S3_PREFIX = "profile-reports"


@dataclass(frozen=True)
class ProfileReportArtifactConfig:
    bucket: str = ""
    prefix: str = DEFAULT_PROFILE_REPORT_S3_PREFIX
    region: str = "ap-south-1"

    @classmethod
    def from_environment(cls) -> "ProfileReportArtifactConfig":
        return cls(
            bucket=os.getenv("PROFILE_REPORT_S3_BUCKET", "").strip(),
            prefix=os.getenv(
                "PROFILE_REPORT_S3_PREFIX",
                DEFAULT_PROFILE_REPORT_S3_PREFIX,
            ).strip("/"),
            region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-south-1",
        )


@dataclass
class ProfileReportArtifactResult:
    pdf_uri: str | None = None
    markdown_uri: str | None = None
    json_uri: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.configured:
            return "disabled"
        if self.pdf_uri and self.json_uri:
            return "succeeded"
        if self.markdown_uri or self.json_uri:
            return "partial"
        return "failed"

    @property
    def configured(self) -> bool:
        return bool(self.pdf_uri or self.markdown_uri or self.json_uri or self.errors)


class ProfileReportArtifactWriter:
    def __init__(
        self,
        *,
        config: ProfileReportArtifactConfig | None = None,
        s3_client=None,
        pdf_renderer: PandocPdfRenderer | None = None,
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
        profile_report: ProfileReportOutput,
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
        result = ProfileReportArtifactResult()
        try:
            pdf_bytes = self.pdf_renderer.render(profile_markdown)
            self._upload(pdf_uri, pdf_bytes, "application/pdf")
            result.pdf_uri = pdf_uri
            logger.info("profile_report_pdf_upload uri=%s bytes=%s", pdf_uri, len(pdf_bytes))
        except Exception as exc:
            result.errors.append(
                f"Failed to write profile report PDF: {exc.__class__.__name__}: "
                f"{exc or '[no message]'}"
            )
            logger.exception(
                "profile_report_pdf_error error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )

        markdown_uri = self._profile_uri(
            student_id=student_id,
            student_name=student_name,
            subject=subject,
            suffix=".md",
        )
        try:
            markdown_bytes = profile_markdown.encode("utf-8")
            self._upload(markdown_uri, markdown_bytes, "text/markdown; charset=utf-8")
            result.markdown_uri = markdown_uri
            logger.info(
                "profile_report_markdown_upload uri=%s bytes=%s",
                markdown_uri,
                len(markdown_bytes),
            )
        except Exception as exc:
            result.errors.append(
                f"Failed to write profile report markdown: {exc.__class__.__name__}: "
                f"{exc or '[no message]'}"
            )
            logger.exception(
                "profile_report_markdown_error error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )

        json_uri = self._profile_uri(
            student_id=student_id,
            student_name=student_name,
            subject=subject,
            suffix=".json",
        )
        try:
            json_bytes = json.dumps(
                profile_report.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self._upload(json_uri, json_bytes, "application/json")
            result.json_uri = json_uri
            logger.info("profile_report_json_upload uri=%s bytes=%s", json_uri, len(json_bytes))
        except Exception as exc:
            result.errors.append(
                f"Failed to write profile report JSON: {exc.__class__.__name__}: "
                f"{exc or '[no message]'}"
            )
            logger.exception(
                "profile_report_json_error error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )

        return result

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
                _safe_path_part(student_id),
                _safe_path_part(student_name),
                "profile_reports",
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
    return normalized or "unknown"


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")
