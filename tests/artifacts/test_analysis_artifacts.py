import unittest
from pathlib import Path
from unittest.mock import Mock

from jee_tutor.artifacts.writer import AnalysisArtifactWriter
from jee_tutor.artifacts.pdf import PANDOC_LATEX_HEADER, PANDOC_PDF_ARGS, PandocPdfRenderer
from jee_tutor.invocation.models import TutorInvocationPayload


class FakePandocConverter:
    def __init__(self, error=None):
        self.error = error
        self.calls = []
        self.header = ""

    def __call__(self, source, to, **kwargs):
        self.calls.append((source, to, kwargs))
        header_arg = next(
            arg for arg in kwargs["extra_args"] if arg.startswith("--include-in-header=")
        )
        self.header = Path(header_arg.split("=", 1)[1]).read_text(encoding="utf-8")
        if self.error:
            raise self.error
        Path(kwargs["outputfile"]).write_bytes(b"%PDF fake pandoc pdf")


class AnalysisPdfRendererTest(unittest.TestCase):
    def test_pandoc_renderer_uses_xelatex_landscape_margin_and_latex_packages(self):
        converter = FakePandocConverter()
        renderer = PandocPdfRenderer(converter=converter)

        pdf_bytes = renderer.render(
            "| Question Number | What You Must Deep-Dive |\n"
            "|---|---|\n"
            "| Q1 | $\\ce{H2 + I2 <=> 2HI}$ and $K_p = K_c(RT)^{\\Delta n}$ |"
        )

        self.assertEqual(pdf_bytes, b"%PDF fake pandoc pdf")
        source, to, kwargs = converter.calls[0]
        self.assertIn("\\ce{H2 + I2 <=> 2HI}", source)
        self.assertEqual(to, "pdf")
        self.assertEqual(kwargs["format"], "markdown+pipe_tables+tex_math_dollars+raw_tex")
        self.assertIn("--pdf-engine=xelatex", kwargs["extra_args"])
        self.assertIn("geometry:landscape", kwargs["extra_args"])
        self.assertIn("geometry:margin=1cm", kwargs["extra_args"])

        self.assertIn("\\usepackage{amsmath}", converter.header)
        self.assertIn("\\usepackage{amssymb}", converter.header)
        self.assertIn("\\usepackage[version=4]{mhchem}", converter.header)
        self.assertIn("\\usepackage{longtable}", converter.header)
        self.assertEqual(
            PANDOC_PDF_ARGS[:4],
            ["--pdf-engine=xelatex", "--standalone", "-V", "geometry:landscape"],
        )
        self.assertIn("mhchem", PANDOC_LATEX_HEADER)


class AnalysisArtifactWriterTest(unittest.TestCase):
    def test_s3_prefix_writes_analysis_pdf_to_same_prefix(self):
        s3_client = Mock()
        writer = AnalysisArtifactWriter(
            s3_client=s3_client,
            pdf_renderer=PandocPdfRenderer(converter=FakePandocConverter()),
        )
        invocation = TutorInvocationPayload(image_s3_prefix="s3://attempt-bucket/maths/student-1/")

        result = writer.write_for_invocation(
            analysis_markdown="| Q | Topic |\n|---|---|\n| 1 | Limits |",
            invocation=invocation,
        )

        self.assertEqual(result.pdf_uri, "s3://attempt-bucket/maths/student-1/analysis.pdf")
        self.assertIsNone(result.markdown_uri)
        self.assertEqual(result.errors, [])
        _, kwargs = s3_client.put_object.call_args
        self.assertEqual(kwargs["Bucket"], "attempt-bucket")
        self.assertEqual(kwargs["Key"], "maths/student-1/analysis.pdf")
        self.assertEqual(kwargs["ContentType"], "application/pdf")
        self.assertTrue(kwargs["Body"].startswith(b"%PDF"))

    def test_s3_uri_writes_analysis_pdf_next_to_image_file(self):
        s3_client = Mock()
        writer = AnalysisArtifactWriter(
            s3_client=s3_client,
            pdf_renderer=PandocPdfRenderer(converter=FakePandocConverter()),
        )
        invocation = TutorInvocationPayload(
            image_s3_uri="s3://attempt-bucket/physics/student-1/page-1.png"
        )

        result = writer.write_for_invocation(
            analysis_markdown="analysis",
            invocation=invocation,
        )

        self.assertEqual(result.pdf_uri, "s3://attempt-bucket/physics/student-1/analysis.pdf")
        _, kwargs = s3_client.put_object.call_args
        self.assertEqual(kwargs["Key"], "physics/student-1/analysis.pdf")

    def test_explicit_output_uri_overrides_input_location(self):
        s3_client = Mock()
        writer = AnalysisArtifactWriter(
            s3_client=s3_client,
            pdf_renderer=PandocPdfRenderer(converter=FakePandocConverter()),
        )
        invocation = TutorInvocationPayload(
            image_s3_prefix="s3://attempt-bucket/maths/",
            analysis_pdf_s3_uri="s3://report-bucket/reports/student-1.pdf",
        )

        result = writer.write_for_invocation(
            analysis_markdown="analysis",
            invocation=invocation,
        )

        self.assertEqual(result.pdf_uri, "s3://report-bucket/reports/student-1.pdf")
        _, kwargs = s3_client.put_object.call_args
        self.assertEqual(kwargs["Bucket"], "report-bucket")
        self.assertEqual(kwargs["Key"], "reports/student-1.pdf")

    def test_non_s3_invocation_does_not_write_artifacts(self):
        s3_client = Mock()
        writer = AnalysisArtifactWriter(
            s3_client=s3_client,
            pdf_renderer=PandocPdfRenderer(converter=FakePandocConverter()),
        )
        invocation = TutorInvocationPayload(image_data_uri="data:image/png;base64,ZmFrZQ==")

        result = writer.write_for_invocation(
            analysis_markdown="analysis",
            invocation=invocation,
        )

        self.assertIsNone(result.pdf_uri)
        self.assertIsNone(result.markdown_uri)
        self.assertEqual(result.errors, [])
        s3_client.put_object.assert_not_called()

    def test_pdf_failure_uploads_markdown_fallback(self):
        s3_client = Mock()
        writer = AnalysisArtifactWriter(
            s3_client=s3_client,
            pdf_renderer=PandocPdfRenderer(converter=FakePandocConverter(RuntimeError("no tex"))),
        )
        invocation = TutorInvocationPayload(image_s3_prefix="s3://attempt-bucket/maths/")

        with self.assertLogs("jee_tutor.artifacts.writer", level="ERROR") as logs:
            result = writer.write_for_invocation(
                analysis_markdown="markdown analysis",
                invocation=invocation,
            )

        self.assertIsNone(result.pdf_uri)
        self.assertEqual(result.markdown_uri, "s3://attempt-bucket/maths/analysis.md")
        self.assertEqual(result.errors, ["Failed to write analysis PDF: RuntimeError: no tex"])
        self.assertTrue(any("analysis_pdf_error" in line for line in logs.output))
        _, kwargs = s3_client.put_object.call_args
        self.assertEqual(kwargs["Key"], "maths/analysis.md")
        self.assertEqual(kwargs["Body"], b"markdown analysis")
        self.assertEqual(kwargs["ContentType"], "text/markdown; charset=utf-8")

    def test_pdf_and_markdown_failures_are_reported(self):
        s3_client = Mock()
        s3_client.put_object.side_effect = RuntimeError("s3 denied")
        writer = AnalysisArtifactWriter(
            s3_client=s3_client,
            pdf_renderer=PandocPdfRenderer(converter=FakePandocConverter(RuntimeError("no tex"))),
        )
        invocation = TutorInvocationPayload(image_s3_prefix="s3://attempt-bucket/maths/")

        result = writer.write_for_invocation(
            analysis_markdown="markdown analysis",
            invocation=invocation,
        )

        self.assertIsNone(result.pdf_uri)
        self.assertIsNone(result.markdown_uri)
        self.assertEqual(
            result.errors,
            [
                "Failed to write analysis PDF: RuntimeError: no tex",
                "Failed to write analysis markdown fallback: RuntimeError: s3 denied",
            ],
        )

    def test_invalid_explicit_output_uri_is_rejected(self):
        writer = AnalysisArtifactWriter(
            s3_client=Mock(),
            pdf_renderer=PandocPdfRenderer(converter=FakePandocConverter()),
        )
        invocation = TutorInvocationPayload(
            image_s3_prefix="s3://attempt-bucket/maths/",
            analysis_pdf_s3_uri="https://example.com/report.pdf",
        )

        with self.assertRaisesRegex(ValueError, "Invalid S3 URI"):
            writer.write_for_invocation(
                analysis_markdown="analysis",
                invocation=invocation,
            )


if __name__ == "__main__":
    unittest.main()
