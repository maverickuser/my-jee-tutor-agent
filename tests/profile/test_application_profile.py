import unittest
from unittest.mock import patch

from boto3.dynamodb.types import TypeSerializer

from jee_tutor.application.profile import StudentProfileApplicationService
from jee_tutor.profile.embeddings import (
    DynamoDbEvidenceEmbeddingStore,
    EvidenceEmbeddingService,
)
from jee_tutor.profile.models import (
    StudentDiagnosisMetadata,
    StructuredDiagnosisQuestionEvidence,
    StructuredDiagnosisReport,
)
from jee_tutor.profile.reporting import ProfileAnalysisService
from jee_tutor.profile.semantic import (
    SemanticCandidateCluster,
    SemanticGapAnalyzer,
    SemanticGapCluster,
)
from jee_tutor.profile.storage import (
    InMemoryStudentDiagnosisMetadataStore,
    InMemoryStructuredDiagnosisArtifactStore,
)
from jee_tutor.tasks.student_profile import PROFILE_REPORT_TASK


def report(report_id: str) -> StructuredDiagnosisReport:
    return StructuredDiagnosisReport(
        diagnosis_report_id=report_id,
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


def metadata(report_id: str) -> StudentDiagnosisMetadata:
    return StudentDiagnosisMetadata(
        student_id="YWuzXTHQ",
        email="student@example.com",
        student_name="Mock_Student",
        subject="Physics",
        test_name="MINOR_TEST_2_Paper_2",
        diagnosis_report_id=report_id,
        diagnosis_date="2026-07-18T10:00:00+00:00",
        diagnosis_json_s3_uri=f"s3://bucket/{report_id}.json",
        question_count=1,
    )


class StudentProfileApplicationServiceTest(unittest.TestCase):
    @patch.dict("os.environ", {"JEE_TUTOR_GIT_SHA": "profile-sha"}, clear=True)
    def test_profile_request_returns_no_history_without_metadata(self):
        service = StudentProfileApplicationService(
            metadata_store=InMemoryStudentDiagnosisMetadataStore(),
            artifact_store=InMemoryStructuredDiagnosisArtifactStore(),
        )

        response = service.handle(
            {
                "task": PROFILE_REPORT_TASK,
                "recipient_email": "student@example.com",
                "subject": "Physics",
            }
        )

        self.assertEqual(response["profile_status"], "no_history")
        self.assertEqual(response["runtime_commit_sha"], "profile-sha")

    @patch.dict("os.environ", {"JEE_TUTOR_GIT_SHA": "profile-sha"}, clear=True)
    def test_profile_request_rejects_missing_email_or_subject(self):
        service = StudentProfileApplicationService(
            metadata_store=InMemoryStudentDiagnosisMetadataStore(),
            artifact_store=InMemoryStructuredDiagnosisArtifactStore(),
        )

        response = service.handle({"task": PROFILE_REPORT_TASK})

        self.assertEqual(response["profile_status"], "invalid_request")
        self.assertIn("Invalid student profile request", response["error"])
        self.assertEqual(response["runtime_commit_sha"], "profile-sha")

    @patch.dict("os.environ", {"JEE_TUTOR_GIT_SHA": "profile-sha"}, clear=True)
    def test_profile_request_generates_written_profile_from_history(self):
        metadata_store = InMemoryStudentDiagnosisMetadataStore()
        artifact_store = InMemoryStructuredDiagnosisArtifactStore()
        for report_id in ["r1", "r2"]:
            metadata_store.put_metadata(metadata(report_id))
            artifact_store.write_report(s3_uri=f"s3://bucket/{report_id}.json", report=report(report_id))
        service = StudentProfileApplicationService(
            metadata_store=metadata_store,
            artifact_store=artifact_store,
            semantic_analyzer=SemanticGapAnalyzer(clusterer=fixed_clusters),
            report_service=ProfileAnalysisService(),
            artifact_writer=FakeProfileArtifactWriter(),
        )

        response = service.handle(
            {
                "task": PROFILE_REPORT_TASK,
                "recipient_email": "student@example.com",
                "subject": "Physics",
            }
        )

        self.assertEqual(response["profile_status"], "succeeded")
        self.assertEqual(response["runtime_commit_sha"], "profile-sha")
        self.assertEqual(response["profile_artifact_status"], "succeeded")
        self.assertEqual(
            response["profile_pdf_uri"],
            "s3://profile-bucket/YWuzXTHQ/Mock_Student/profile_reports/Physics_profile_report.pdf",
        )
        self.assertEqual(response["profile_artifact_errors"], [])
        self.assertIn("Physics Longitudinal Profile", response["profile_markdown"])
        self.assertIn("Projectile components", response["profile_markdown"])

    def test_profile_request_creates_dynamodb_embeddings_before_semantic_classification(self):
        metadata_store = InMemoryStudentDiagnosisMetadataStore()
        artifact_store = InMemoryStructuredDiagnosisArtifactStore()
        for report_id in ["r1", "r2"]:
            metadata_store.put_metadata(metadata(report_id))
            artifact_store.write_report(s3_uri=f"s3://bucket/{report_id}.json", report=report(report_id))
        embedding_table = SerializingDynamoTable()
        classifier = RecordingSemanticClassifier()
        embedding_service = EvidenceEmbeddingService(
            store=DynamoDbEvidenceEmbeddingStore(
                table_name="embedding-table",
                region="ap-south-1",
            ),
            client=SequentialEmbeddingClient([[1.0, 0.0], [0.9, 0.1]]),
        )
        service = StudentProfileApplicationService(
            metadata_store=metadata_store,
            artifact_store=artifact_store,
            semantic_analyzer=SemanticGapAnalyzer(
                embedding_service=embedding_service,
                classifier=classifier,
                similarity_threshold=0.95,
            ),
            report_service=ProfileAnalysisService(),
            artifact_writer=FakeProfileArtifactWriter(),
        )

        with patch(
            "jee_tutor.profile.embeddings.boto3.resource",
            return_value=FakeDynamoResource(embedding_table),
        ):
            response = service.handle(
                {
                    "task": PROFILE_REPORT_TASK,
                    "recipient_email": "student@example.com",
                    "subject": "Physics",
                }
            )

        self.assertEqual(response["profile_status"], "succeeded")
        self.assertEqual(len(embedding_table.put_items), 2)
        self.assertEqual(classifier.seen_candidates[0].evidence_ids, ["r1:q1", "r2:q1"])


def fixed_clusters(_items):
    return [
        SemanticGapCluster(
            cluster_id="cluster-1",
            cluster_type="same_underlying_gap",
            title="Projectile components",
            evidence_ids=["r1:q1", "r2:q1"],
            rationale="same gap",
        )
    ]


class SequentialEmbeddingClient:
    model = "fake-embedding"

    def __init__(self, vectors: list[list[float]]):
        self.vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.vectors


class RecordingSemanticClassifier:
    def __init__(self):
        self.seen_candidates: list[SemanticCandidateCluster] = []

    def classify(
        self,
        *,
        evidence_items,
        candidates: list[SemanticCandidateCluster],
    ) -> list[SemanticGapCluster]:
        self.seen_candidates = candidates
        return [
            SemanticGapCluster(
                cluster_id="cluster-1",
                cluster_type="same_underlying_gap",
                title="Projectile components",
                evidence_ids=[item.evidence_id for item in evidence_items],
                rationale="LLM classified these cosine-near gaps as the same underlying gap.",
            )
        ]


class FakeProfileArtifactResult:
    status = "succeeded"
    pdf_uri = "s3://profile-bucket/YWuzXTHQ/Mock_Student/profile_reports/Physics_profile_report.pdf"
    markdown_uri = "s3://profile-bucket/YWuzXTHQ/Mock_Student/profile_reports/Physics_profile_report.md"
    json_uri = "s3://profile-bucket/YWuzXTHQ/Mock_Student/profile_reports/Physics_profile_report.json"
    errors = []


class FakeProfileArtifactWriter:
    def __init__(self):
        self.calls = []

    def write(self, **kwargs):
        self.calls.append(kwargs)
        return FakeProfileArtifactResult()


class SerializingDynamoTable:
    def __init__(self):
        self.items = {}
        self.put_items = []
        self.serializer = TypeSerializer()

    def get_item(self, *, Key):
        item = self.items.get((Key["diagnosis_json_s3_uri"], Key["embedding_key"]))
        return {"Item": item} if item else {}

    def put_item(self, *, Item):
        for value in Item.values():
            self.serializer.serialize(value)
        self.items[(Item["diagnosis_json_s3_uri"], Item["embedding_key"])] = Item
        self.put_items.append(Item)


class FakeDynamoResource:
    def __init__(self, table):
        self.table = table

    def Table(self, _table_name):
        return self.table


if __name__ == "__main__":
    unittest.main()
