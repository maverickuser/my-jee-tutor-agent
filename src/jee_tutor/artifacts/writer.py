from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import urlparse

import boto3

from jee_tutor.artifacts.pdf import PandocPdfRenderer
from jee_tutor.invocation.models import TutorInvocationPayload


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
            print(f"analysis_pdf_upload uri={pdf_uri} bytes={len(pdf_bytes)}")
            return result
        except Exception as exc:
            result.errors.append(
                f"Failed to write analysis PDF: {exc.__class__.__name__}: {exc or '[no message]'}"
            )
            print(f"analysis_pdf_error error_type={exc.__class__.__name__} error={exc}")

        markdown_uri = self._markdown_uri_for_pdf_uri(pdf_uri)
        try:
            markdown_bytes = analysis_markdown.encode("utf-8")
            self._upload(markdown_uri, markdown_bytes, "text/markdown; charset=utf-8")
            result.markdown_uri = markdown_uri
            print(f"analysis_markdown_upload uri={markdown_uri} bytes={len(markdown_bytes)}")
        except Exception as exc:
            result.errors.append(
                f"Failed to write analysis markdown fallback: {exc.__class__.__name__}: "
                f"{exc or '[no message]'}"
            )
            print(f"analysis_markdown_error error_type={exc.__class__.__name__} error={exc}")

        return result

    @classmethod
    def _resolve_pdf_uri(cls, invocation: TutorInvocationPayload) -> str | None:
        if invocation.analysis_pdf_s3_uri:
            cls._parse_s3_uri(invocation.analysis_pdf_s3_uri)
            return invocation.analysis_pdf_s3_uri
        if invocation.image_s3_prefix:
            bucket, prefix = cls._parse_s3_uri(invocation.image_s3_prefix)
            normalized_prefix = prefix.rstrip("/")
            key = f"{normalized_prefix}/analysis.pdf" if normalized_prefix else "analysis.pdf"
            return f"s3://{bucket}/{key}"
        if invocation.image_s3_uri:
            bucket, key = cls._parse_s3_uri(invocation.image_s3_uri)
            parent = PurePosixPath(key).parent
            output_key = str(parent / "analysis.pdf") if str(parent) != "." else "analysis.pdf"
            return f"s3://{bucket}/{output_key}"
        return None

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
