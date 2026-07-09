from pathlib import Path
import tempfile
import unittest

from scripts.build_curriculum_taxonomy import (
    BuildCurriculumTaxonomyConfig,
    build_curriculum_taxonomy,
)


class Body:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data


class FakeS3:
    def __init__(self, body: bytes = b"%PDF"):
        self.body = body
        self.put_calls = []

    def get_object(self, **kwargs):
        if not self.body:
            return {"Body": Body(b""), "ETag": "empty"}
        return {"Body": Body(self.body), "ETag": "source-etag"}

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {}


def valid_draft(source_documents, version):
    return {
        "version": version,
        "source_documents": [
            {
                "subject": document.get("subject"),
                "uri": document["uri"],
                "etag": document.get("etag"),
            }
            for document in source_documents
        ],
        "subjects": {
            "Physics": {
                "chapters": {
                    "Electrostatics": {
                        "aliases": [],
                        "topics": {"Capacitance": {"aliases": []}},
                    }
                }
            }
        },
    }


class BuildCurriculumTaxonomyTest(unittest.TestCase):
    def config(self, artifact_path: str, publish: bool = False):
        return BuildCurriculumTaxonomyConfig(
            source_pdf_s3_uris=["s3://bucket/physics.pdf"],
            output_s3_uri="s3://bucket/curriculum/taxonomy.json",
            taxonomy_version="2026-01",
            publish_taxonomy=publish,
            artifact_path=artifact_path,
        )

    def test_missing_source_pdfs_fail_before_publish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "SOURCE_PDF"):
                build_curriculum_taxonomy(
                    BuildCurriculumTaxonomyConfig(
                        source_pdf_s3_uris=[],
                        output_s3_uri="s3://bucket/out.json",
                        taxonomy_version="2026-01",
                        artifact_path=str(Path(tmpdir) / "taxonomy.json"),
                    ),
                    s3_client=FakeS3(),
                    extractor=valid_draft,
                )

    def test_empty_source_pdf_fails_before_publish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_s3 = FakeS3(body=b"")
            with self.assertRaisesRegex(ValueError, "empty"):
                build_curriculum_taxonomy(
                    self.config(str(Path(tmpdir) / "taxonomy.json"), publish=True),
                    s3_client=fake_s3,
                    extractor=valid_draft,
                )
            self.assertEqual(fake_s3.put_calls, [])

    def test_invalid_taxonomy_fails_before_publish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_s3 = FakeS3()
            with self.assertRaises(ValueError):
                build_curriculum_taxonomy(
                    self.config(str(Path(tmpdir) / "taxonomy.json"), publish=True),
                    s3_client=fake_s3,
                    extractor=lambda source_documents, version: {
                        "version": version,
                        "source_documents": [],
                        "subjects": {},
                    },
                )
            self.assertEqual(fake_s3.put_calls, [])

    def test_valid_taxonomy_writes_artifact_without_publish_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = Path(tmpdir) / "taxonomy.json"
            fake_s3 = FakeS3()

            taxonomy = build_curriculum_taxonomy(
                self.config(str(artifact)),
                s3_client=fake_s3,
                extractor=valid_draft,
            )

            self.assertEqual(taxonomy.version, "2026-01")
            self.assertTrue(artifact.exists())
            self.assertEqual(fake_s3.put_calls, [])

    def test_valid_taxonomy_publishes_only_when_approved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_s3 = FakeS3()

            build_curriculum_taxonomy(
                self.config(str(Path(tmpdir) / "taxonomy.json"), publish=True),
                s3_client=fake_s3,
                extractor=valid_draft,
            )

            self.assertEqual(len(fake_s3.put_calls), 1)
            self.assertEqual(fake_s3.put_calls[0]["Bucket"], "bucket")
            self.assertEqual(fake_s3.put_calls[0]["Key"], "curriculum/taxonomy.json")


if __name__ == "__main__":
    unittest.main()
