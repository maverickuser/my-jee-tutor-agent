from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import PurePosixPath
import re
from urllib.parse import urlparse

import boto3

from jee_tutor.artifacts.pdf import PandocPdfRenderer
from jee_tutor.invocation.models import TutorInvocationPayload


logger = logging.getLogger(__name__)


@dataclass
class AnalysisArtifactResult:
    pdf_uri: str | None = None
    markdown_uri: str | None = None
    errors: list[str] = field(default_factory=list)


class AnalysisArtifactWriter:
    def __init__(
        self,
        *,
        s3_client=None,
        pdf_renderer: PandocPdfRenderer | None = None,
    ):
        self.s3_client = s3_client
        self.pdf_renderer = pdf_renderer or PandocPdfRenderer()

    def write_for_invocation(
        self,
        *,
        analysis_markdown: str,
        invocation: TutorInvocationPayload,
    ) -> AnalysisArtifactResult:
        pdf_uri = self._resolve_pdf_uri(invocation)
        if not pdf_uri:
            return AnalysisArtifactResult()

        result = AnalysisArtifactResult()
        try:
            pdf_bytes = self.pdf_renderer.render(analysis_markdown)
            self._upload(pdf_uri, pdf_bytes, "application/pdf")
            result.pdf_uri = pdf_uri
            logger.info("analysis_pdf_upload uri=%s bytes=%s", pdf_uri, len(pdf_bytes))
            return result
        except Exception as exc:
            result.errors.append(
                f"Failed to write analysis PDF: {exc.__class__.__name__}: {exc or '[no message]'}"
            )
            logger.exception(
                "analysis_pdf_error error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )

        markdown_uri = self._markdown_uri_for_pdf_uri(pdf_uri)
        try:
            markdown_bytes = analysis_markdown.encode("utf-8")
            self._upload(markdown_uri, markdown_bytes, "text/markdown; charset=utf-8")
            result.markdown_uri = markdown_uri
            logger.info(
                "analysis_markdown_upload uri=%s bytes=%s",
                markdown_uri,
                len(markdown_bytes),
            )
        except Exception as exc:
            result.errors.append(
                f"Failed to write analysis markdown fallback: {exc.__class__.__name__}: "
                f"{exc or '[no message]'}"
            )
            logger.exception(
                "analysis_markdown_error error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )

        return result

    @classmethod
    def _resolve_pdf_uri(cls, invocation: TutorInvocationPayload) -> str | None:
        if invocation.image_s3_prefix:
            bucket, prefix = cls._parse_s3_uri(invocation.image_s3_prefix)
            normalized_prefix = prefix.rstrip("/")
            filename = cls._analysis_pdf_filename(invocation.subject)
            key = f"{normalized_prefix}/{filename}" if normalized_prefix else filename
            return f"s3://{bucket}/{key}"
        return None

    @staticmethod
    def _analysis_pdf_filename(subject: str | None) -> str:
        if not subject:
            return "analysis.pdf"
        normalized_subject = re.sub(r"[^A-Za-z0-9._-]+", "_", subject.strip()).strip("._-")
        if not normalized_subject:
            return "analysis.pdf"
        return f"{normalized_subject}_analysis.pdf"

    @classmethod
    def _markdown_uri_for_pdf_uri(cls, pdf_uri: str) -> str:
        bucket, key = cls._parse_s3_uri(pdf_uri)
        path = PurePosixPath(key)
        markdown_key = str(path.with_suffix(".md"))
        return f"s3://{bucket}/{markdown_key}"

    def _upload(self, s3_uri: str, body: bytes, content_type: str) -> None:
        bucket, key = self._parse_s3_uri(s3_uri)
        self._s3().put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def _s3(self):
        if self.s3_client is None:
            self.s3_client = boto3.client("s3")
        return self.s3_client

    @staticmethod
    def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
        parsed = urlparse(s3_uri)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError(f"Invalid S3 URI: {s3_uri}")
        return parsed.netloc, parsed.path.lstrip("/")
