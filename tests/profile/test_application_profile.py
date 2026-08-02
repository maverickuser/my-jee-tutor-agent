import unittest
from contextlib import contextmanager
from unittest.mock import patch

from boto3.dynamodb.types import TypeSerializer

from jee_tutor.application.profile import StudentProfileApplicationService
from jee_tutor.profile.embeddings import (
    DynamoDbEvidenceEmbeddingStore,
    EvidenceEmbeddingService,
)
from jee_tutor.profile.hierarchical import (
    CandidateRelationshipDecision,
    ConceptualStrand,
    ConceptualStrandAnalyzer,
    ConceptualStrandOutput,
    StrandManifestation,
)
from jee_tutor.profile.models import (
    StudentDiagnosisMetadata,
    StructuredDiagnosisQuestionEvidence,
    StructuredDiagnosisReport,
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
        observability = RecordingProfileObservability()
        service = StudentProfileApplicationService(
            metadata_store=metadata_store,
            artifact_store=artifact_store,
            conceptual_strand_analyzer=ConceptualStrandAnalyzer(
                analyzer=fixed_strands
            ),
            artifact_writer=FakeProfileArtifactWriter(),
            observability=observability,
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
            response["profile_report_pdf_uri"],
            "s3://profile-bucket/profile-reports/Mock_Student+YWuzXTHQ/Physics/Physics_profile_report.pdf",
        )
        self.assertEqual(response["profile_artifact_errors"], [])
        self.assertIn("What to do differently next time", response["profile_markdown"])
        self.assertIn("**Do:**", response["profile_markdown"])
        self.assertIn("**Ask this when you see:**", response["profile_markdown"])
        self.assertNotIn("r1:q1", response["profile_markdown"])
        self.assertEqual(len(response["profile_internal_metadata"]["insights"]), 1)
        self.assertEqual(observability.input_payload["task"], "profile")
        self.assertNotIn("recipient_email", observability.input_payload)
        self.assertEqual(
            observability.observation.updates[0]["output"]["profile_status"],
            "succeeded",
        )

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
            conceptual_strand_analyzer=ConceptualStrandAnalyzer(
                embedding_service=embedding_service,
                classifier=classifier,
                similarity_floor=0.95,
            ),
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
        self.assertEqual(
            (
                classifier.seen_candidate_pairs[0].left_evidence_id,
                classifier.seen_candidate_pairs[0].right_evidence_id,
            ),
            ("r1:q1", "r2:q1"),
        )


def fixed_strands(_items):
    return ConceptualStrandOutput(
        strands=[
        ConceptualStrand(
            strand_id="strand-1",
            chapter_family="Kinematics",
            chapter_labels=["Kinematics"],
            topics=["Projectile motion"],
            title="Projectile components",
            missing_mental_model="Independent horizontal and vertical motion",
            shared_failure="Treats projectile speed as constant.",
            corrective_model="Resolve acceleration and velocity by component.",
            evidence_ids=["r1:q1", "r2:q1"],
            manifestations=[
                StrandManifestation(
                    evidence_id=evidence_id,
                    manifestation="Did not update the vertical velocity component.",
                )
                for evidence_id in ["r1:q1", "r2:q1"]
            ],
            confidence="high",
            rationale="One component model corrects both manifestations.",
        )
        ],
    )


class SequentialEmbeddingClient:
    model = "fake-embedding"

    def __init__(self, vectors: list[list[float]]):
        self.vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.vectors


class RecordingSemanticClassifier:
    def __init__(self):
        self.seen_candidate_pairs = []

    def classify(
        self,
        *,
        evidence_items,
        candidate_pairs,
    ) -> ConceptualStrandOutput:
        self.seen_candidate_pairs = candidate_pairs
        return ConceptualStrandOutput(
            relationships=[
                CandidateRelationshipDecision(
                    candidate_pair_id=pair.pair_id,
                    relationship="same_underlying_gap",
                    rationale="Both failures reflect the same component model.",
                )
                for pair in candidate_pairs
            ],
            strands=[
            ConceptualStrand(
                strand_id="strand-1",
                chapter_family="Kinematics",
                chapter_labels=["Kinematics"],
                topics=["Projectile motion"],
                title="Projectile components",
                missing_mental_model="Independent horizontal and vertical motion",
                shared_failure="Treats projectile speed as constant.",
                corrective_model="Resolve acceleration and velocity by component.",
                evidence_ids=[item.evidence_id for item in evidence_items],
                manifestations=[
                    StrandManifestation(
                        evidence_id=item.evidence_id,
                        manifestation="Did not update vertical velocity.",
                    )
                    for item in evidence_items
                ],
                confidence="high",
                rationale="One component model corrects all manifestations.",
            )
            ]
        )


class RecordingProfileObservation:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class RecordingProfileObservability:
    def __init__(self):
        self.input_payload = None
        self.observation = RecordingProfileObservation()

    @contextmanager
    def invocation_span(self, *, input_payload, **_kwargs):
        self.input_payload = input_payload
        yield self.observation


class FakeProfileArtifactResult:
    status = "succeeded"
    pdf_uri = "s3://profile-bucket/profile-reports/Mock_Student+YWuzXTHQ/Physics/Physics_profile_report.pdf"
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
