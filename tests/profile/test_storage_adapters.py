import json
import unittest
from unittest.mock import Mock, patch

from jee_tutor.profile.models import (
    StudentDiagnosisMetadata,
    StructuredDiagnosisQuestionEvidence,
    StructuredDiagnosisReport,
)
from jee_tutor.profile.storage import (
    DynamoDbStudentDiagnosisMetadataStore,
    NullStudentDiagnosisMetadataStore,
    S3StructuredDiagnosisArtifactStore,
    StudentDiagnosisMetadataConfig,
    StructuredDiagnosisArtifactConfig,
    build_structured_diagnosis_artifact_store,
    build_student_diagnosis_metadata_store,
)


class Body:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self):
        return self.payload


def report() -> StructuredDiagnosisReport:
    return StructuredDiagnosisReport(
        diagnosis_report_id="report-1",
        student_id="YWuzXTHQ",
        student_name="Mock_Student",
        subject="Physics",
        test_name="MINOR_TEST_2_Paper_2",
        diagnosis_date="2026-07-18T10:00:00+00:00",
        questions=[
            StructuredDiagnosisQuestionEvidence(
                question_number="1",
                chapter="Kinematics",
                topic="Projectile motion",
                what_you_thought="You likely used constant speed.",
                why_that_thought_is_wrong="Vertical acceleration changes velocity.",
                exact_concept_gap="Projectile components",
                what_you_must_deep_dive="Resolve horizontal and vertical motion.",
            )
        ],
    )


def metadata() -> StudentDiagnosisMetadata:
    return StudentDiagnosisMetadata(
        student_id="YWuzXTHQ",
        email="student@example.com",
        student_name="Mock_Student",
        subject="Physics",
        test_name="MINOR_TEST_2_Paper_2",
        diagnosis_report_id="report-1",
        diagnosis_date="2026-07-18T10:00:00+00:00",
        diagnosis_json_s3_uri="s3://bucket/report.json",
        question_count=1,
    )


class ProfileStorageAdaptersTest(unittest.TestCase):
    def test_null_metadata_store_noops_and_queries_empty(self):
        store = NullStudentDiagnosisMetadataStore()

        store.put_metadata(metadata())

        self.assertEqual(
            store.query_by_email_subject(email="student@example.com", subject="Physics"),
            [],
        )

    def test_metadata_config_from_environment_disables_without_table(self):
        with patch.dict("os.environ", {}, clear=True):
            config = StudentDiagnosisMetadataConfig.from_environment()

        self.assertFalse(config.enabled)
        self.assertEqual(config.table_name, "")

    def test_metadata_config_from_environment_enables_with_table(self):
        with patch.dict(
            "os.environ",
            {
                "STUDENT_DIAGNOSIS_METADATA_TABLE_NAME": "student-table",
                "AWS_REGION": "us-east-1",
            },
            clear=True,
        ):
            config = StudentDiagnosisMetadataConfig.from_environment()

        self.assertTrue(config.enabled)
        self.assertEqual(config.table_name, "student-table")
        self.assertEqual(config.region, "us-east-1")

    def test_build_metadata_store_returns_null_when_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsInstance(
                build_student_diagnosis_metadata_store(),
                NullStudentDiagnosisMetadataStore,
            )

    def test_dynamodb_metadata_store_puts_and_queries_records(self):
        table = Mock()
        stored_item = metadata().model_dump(exclude_none=True)
        stored_item["subject_report_key"] = "physics#2026-07-18T10:00:00+00:00#report-1"
        table.query.return_value = {"Items": [stored_item]}
        resource = Mock()
        resource.Table.return_value = table
        store = DynamoDbStudentDiagnosisMetadataStore(
            table_name="student-table",
            region="ap-south-1",
        )

        with patch("jee_tutor.profile.storage.boto3.resource", return_value=resource):
            store.put_metadata(metadata())
            records = store.query_by_email_subject(
                email="STUDENT@example.com",
                subject="Physics",
            )

        self.assertEqual(table.put_item.call_count, 1)
        item = table.put_item.call_args.kwargs["Item"]
        self.assertEqual(item["email"], "student@example.com")
        self.assertTrue(item["subject_report_key"].startswith("physics#"))
        self.assertEqual(records[0].diagnosis_report_id, "report-1")
        self.assertEqual(
            table.query.call_args.kwargs["ExpressionAttributeValues"][":subject_prefix"],
            "physics#",
        )

    def test_s3_artifact_store_writes_and_loads_report(self):
        s3_client = Mock()
        s3_client.get_object.return_value = {
            "Body": Body(json.dumps(report().model_dump(mode="json")).encode("utf-8"))
        }
        store = S3StructuredDiagnosisArtifactStore(
            region="ap-south-1",
            s3_client=s3_client,
        )

        store.write_report(s3_uri="s3://bucket/path/report.json", report=report())
        loaded = store.load_report(s3_uri="s3://bucket/path/report.json")

        self.assertEqual(loaded.diagnosis_report_id, "report-1")
        self.assertEqual(s3_client.put_object.call_args.kwargs["Bucket"], "bucket")
        self.assertEqual(s3_client.put_object.call_args.kwargs["Key"], "path/report.json")
        self.assertEqual(s3_client.put_object.call_args.kwargs["ContentType"], "application/json")

    def test_s3_artifact_store_rejects_invalid_uri(self):
        store = S3StructuredDiagnosisArtifactStore(region="ap-south-1", s3_client=Mock())

        with self.assertRaisesRegex(ValueError, "Invalid S3 URI"):
            store.load_report(s3_uri="not-s3")

    def test_artifact_config_and_builder_use_environment_region(self):
        with patch.dict("os.environ", {"AWS_DEFAULT_REGION": "us-west-2"}, clear=True):
            config = StructuredDiagnosisArtifactConfig.from_environment()
            built = build_structured_diagnosis_artifact_store()

        self.assertEqual(config.region, "us-west-2")
        self.assertIsInstance(built, S3StructuredDiagnosisArtifactStore)


if __name__ == "__main__":
    unittest.main()
