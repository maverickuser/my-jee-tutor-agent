from pathlib import Path
import tempfile
import unittest

from botocore.exceptions import ClientError

from scripts.publish_chapter_weightage import publish_chapter_weightage


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.put_calls = []

    def head_object(self, *, Bucket, Key):
        item = self.objects.get((Bucket, Key))
        if item is None:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "missing"}},
                "HeadObject",
            )
        return {"Metadata": item["Metadata"]}

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs


def write_subject(path: Path, subject: str, weight: float = 5.0) -> None:
    path.write_text(
        "{"
        '"schema_version":"1.0",'
        f'"subject":"{subject}",'
        '"chapters":['
        f'{{"rank":1,"chapter":"Chapter","combined_weightage_percent":{weight}}}'
        "]"
        "}"
    )


class PublishChapterWeightageTest(unittest.TestCase):
    def test_uploads_all_subject_files_to_stable_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_subject(root / "chemistry.json", "Chemistry")
            write_subject(root / "maths.json", "Maths")
            write_subject(root / "physics.json", "Physics")
            s3 = FakeS3()

            result = publish_chapter_weightage(source_dir=root, s3_client=s3)

        self.assertEqual(len(result), 3)
        self.assertEqual(len(s3.put_calls), 3)
        self.assertEqual(
            {call["Key"] for call in s3.put_calls},
            {
                "curriculum/chapter-weightage/chemistry.json",
                "curriculum/chapter-weightage/maths.json",
                "curriculum/chapter-weightage/physics.json",
            },
        )
        self.assertTrue(all(call["ContentType"] == "application/json" for call in s3.put_calls))

    def test_second_publish_skips_unchanged_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_subject(root / "chemistry.json", "Chemistry")
            write_subject(root / "maths.json", "Maths")
            write_subject(root / "physics.json", "Physics")
            s3 = FakeS3()
            publish_chapter_weightage(source_dir=root, s3_client=s3)

            result = publish_chapter_weightage(source_dir=root, s3_client=s3)

        self.assertEqual(len(s3.put_calls), 3)
        self.assertTrue(all(not item["uploaded"] for item in result))
        self.assertTrue(all(item["reason"] == "unchanged" for item in result))

    def test_rejects_non_descending_weightage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chemistry.json").write_text(
                '{"schema_version":"1.0","subject":"Chemistry","chapters":['
                '{"rank":1,"chapter":"A","combined_weightage_percent":2},'
                '{"rank":2,"chapter":"B","combined_weightage_percent":3}]}'
            )
            write_subject(root / "maths.json", "Maths")
            write_subject(root / "physics.json", "Physics")

            with self.assertRaisesRegex(ValueError, "descending"):
                publish_chapter_weightage(source_dir=root, s3_client=FakeS3())


if __name__ == "__main__":
    unittest.main()
