from pathlib import Path
import tempfile
import unittest

from botocore.exceptions import ClientError

from scripts.publish_curriculum_taxonomy import publish_curriculum_taxonomy


class Body:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data


class FakeS3:
    def __init__(self, existing_body: bytes | None = None, missing_bucket: bool = False):
        self.existing_body = existing_body
        self.missing_bucket = missing_bucket
        self.put_calls = []

    def get_object(self, **kwargs):
        if self.missing_bucket:
            raise ClientError(
                {"Error": {"Code": "NoSuchBucket", "Message": "missing bucket"}},
                "GetObject",
            )
        if self.existing_body is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )
        return {"Body": Body(self.existing_body)}

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        self.existing_body = kwargs["Body"]
        return {}


def taxonomy_json(version: str = "2026-01", topic: str = "Kinematics") -> bytes:
    return (
        "{"
        f'"version":"{version}",'
        '"subjects":{"Physics":{"chapters":{"Motion":{"topics":{'
        f'"{topic}":{{"aliases":[]}}'
        "}}}}}"
        "}"
    ).encode()


class PublishCurriculumTaxonomyTest(unittest.TestCase):
    def test_missing_remote_uploads_valid_taxonomy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "taxonomy.json"
            path.write_bytes(taxonomy_json())
            s3 = FakeS3()

            result = publish_curriculum_taxonomy(
                taxonomy_file=path,
                s3_uri="s3://bucket/curriculum/jee_curriculum_taxonomy.json",
                s3_client=s3,
            )

            self.assertTrue(result["uploaded"])
            self.assertEqual(result["reason"], "missing")
            self.assertEqual(len(s3.put_calls), 1)
            self.assertEqual(s3.put_calls[0]["ContentType"], "application/json")
            self.assertEqual(s3.put_calls[0]["Metadata"]["taxonomy-version"], "2026-01")

    def test_same_remote_version_and_checksum_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            body = taxonomy_json()
            path = Path(tmpdir) / "taxonomy.json"
            path.write_bytes(body)
            s3 = FakeS3(existing_body=body)

            result = publish_curriculum_taxonomy(
                taxonomy_file=path,
                s3_uri="s3://bucket/curriculum/jee_curriculum_taxonomy.json",
                s3_client=s3,
            )

            self.assertFalse(result["uploaded"])
            self.assertEqual(result["reason"], "unchanged")
            self.assertEqual(s3.put_calls, [])

    def test_changed_remote_uploads_stable_runtime_object(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "taxonomy.json"
            path.write_bytes(taxonomy_json(version="2026-02"))
            s3 = FakeS3(existing_body=taxonomy_json(version="2026-01"))

            result = publish_curriculum_taxonomy(
                taxonomy_file=path,
                s3_uri="s3://bucket/curriculum/jee_curriculum_taxonomy.json",
                s3_client=s3,
            )

        self.assertTrue(result["uploaded"])
        self.assertEqual(result["reason"], "changed")
        self.assertEqual(result["previous_version"], "2026-01")
        self.assertEqual(len(s3.put_calls), 1)

    def test_missing_bucket_error_is_actionable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "taxonomy.json"
            path.write_bytes(taxonomy_json())
            s3 = FakeS3(missing_bucket=True)

            with self.assertRaisesRegex(
                RuntimeError,
                "Configured curriculum taxonomy bucket does not exist: missing-bucket",
            ):
                publish_curriculum_taxonomy(
                    taxonomy_file=path,
                    s3_uri="s3://missing-bucket/curriculum/jee_curriculum_taxonomy.json",
                    s3_client=s3,
                )


if __name__ == "__main__":
    unittest.main()
