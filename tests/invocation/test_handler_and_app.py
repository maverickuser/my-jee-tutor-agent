import unittest
import sys
from unittest.mock import patch

from jee_tutor.handler import validate_tutor_invocation


class HandlerAndAppTest(unittest.TestCase):
    def test_validate_tutor_invocation_returns_model(self):
        payload = validate_tutor_invocation({"image_data_uri": "data:image/png;base64,ZmFrZQ=="})

        self.assertEqual(payload.image_data_uri, "data:image/png;base64,ZmFrZQ==")

    def test_invocation_models_do_not_import_profile_report_stack(self):
        sys.modules.pop("jee_tutor.profile.reporting", None)
        sys.modules.pop("jee_tutor.application.profile", None)

        from jee_tutor.invocation.models import AgentLLMCallRecord

        self.assertEqual(AgentLLMCallRecord.__name__, "AgentLLMCallRecord")
        self.assertNotIn("jee_tutor.profile.reporting", sys.modules)
        self.assertNotIn("jee_tutor.application.profile", sys.modules)

    def test_validate_tutor_invocation_accepts_agentcore_json_contract(self):
        payload = validate_tutor_invocation(
            {
                "task": "diagnose this attempt",
                "subject": "maths",
                "image_s3_prefix": "s3://attempt-bucket/maths/attempt-123/",
            }
        )

        self.assertEqual(payload.resolved_question_context, "diagnose this attempt")
        self.assertEqual(payload.image_s3_prefix, "s3://attempt-bucket/maths/attempt-123/")
        self.assertEqual(payload.subject, "maths")

    def test_validate_tutor_invocation_accepts_profile_without_image_source(self):
        payload = validate_tutor_invocation(
            {
                "task": "profile",
                "recipient_email": "student@example.com",
                "subject": "Physics",
            }
        )

        self.assertEqual(payload.task, "profile")
        self.assertEqual(payload.recipient_email, "student@example.com")
        self.assertIsNone(payload.image_s3_prefix)
        self.assertIsNone(payload.image_data_uri)

    def test_validate_tutor_invocation_accepts_profile_task_aliases_without_image_source(self):
        for task in ["Profile", "profile ", "profile-report", "student_profile", "task profile"]:
            with self.subTest(task=task):
                payload = validate_tutor_invocation(
                    {
                        "task": task,
                        "recipient_email": "student@example.com",
                        "subject": "Physics",
                    }
                )

                self.assertEqual(payload.task, task)
                self.assertIsNone(payload.image_s3_prefix)
                self.assertIsNone(payload.image_data_uri)

    def test_validate_tutor_invocation_still_rejects_diagnosis_without_image_source(self):
        with self.assertRaises(Exception):
            validate_tutor_invocation(
                {
                    "task": "diagnose this attempt",
                    "recipient_email": "student@example.com",
                    "subject": "Physics",
                }
            )

    def test_safe_trace_input_redacts_student_metadata_in_s3_prefix(self):
        payload = validate_tutor_invocation(
            {
                "image_s3_prefix": (
                    "s3://attempt-bucket/users/YWuzXTHQ/Mock_Student/tests/"
                    "MINOR_TEST_2_Paper_2/subjects/Physics/questions/"
                ),
                "recipient_email": "student@example.com",
            }
        )

        trace_input = payload.safe_trace_input()

        self.assertNotIn("recipient_email", trace_input)
        self.assertNotIn("YWuzXTHQ", trace_input["image_s3_prefix"])
        self.assertNotIn("Mock_Student", trace_input["image_s3_prefix"])
        self.assertNotIn("MINOR_TEST_2_Paper_2", trace_input["image_s3_prefix"])
        self.assertIn("[student-id]", trace_input["image_s3_prefix"])

    def test_validate_tutor_invocation_rejects_invalid_recipient_email(self):
        with self.assertRaises(Exception):
            validate_tutor_invocation(
                {
                    "image_s3_prefix": "s3://attempt-bucket/maths/attempt-123/",
                    "recipient_email": "not-an-email",
                }
            )

    def test_validate_tutor_invocation_rejects_legacy_extra_fields(self):
        with self.assertRaises(Exception):
            validate_tutor_invocation(
                {
                    "task": "diagnose this attempt",
                    "image_s3_prefix": "s3://attempt-bucket/maths/attempt-123/",
                    "image_folder": "/app/input/attempt-images",
                }
            )

    def test_agentcore_app_entrypoint_delegates_to_handler(self):
        with patch("jee_tutor.app.handle_agentcore_request", return_value={"analysis": "ok"}):
            from agentcore_app import invoke_tutor

            self.assertEqual(invoke_tutor({"image_data_uri": "x"}, None), {"analysis": "ok"})

    def test_agentcore_handler_dispatches_profile_report_task(self):
        with patch("jee_tutor.infrastructure.composition.build_student_profile_service") as build_profile:
            build_profile.return_value.handle.return_value = {"profile_status": "no_history"}
            from jee_tutor.handler import handle_agentcore_request

            response = handle_agentcore_request(
                {
                    "task": "profile",
                    "recipient_email": "student@example.com",
                    "subject": "Physics",
                }
            )

        self.assertEqual(response, {"profile_status": "no_history"})

    def test_agentcore_profile_task_runs_embedding_semantic_flow(self):
        from jee_tutor.application.profile import StudentProfileApplicationService
        from jee_tutor.profile.embeddings import (
            EvidenceEmbeddingRecord,
            EvidenceEmbeddingService,
            build_embedding_input_text,
            build_embedding_key,
            embedding_text_hash,
        )
        from jee_tutor.profile.reporting import ProfileAnalysisService
        from jee_tutor.profile.semantic import SemanticGapAnalyzer
        from jee_tutor.profile.storage import (
            InMemoryStudentDiagnosisMetadataStore,
            InMemoryStructuredDiagnosisArtifactStore,
        )
        from tests.profile.test_application_profile import metadata, report

        metadata_store = InMemoryStudentDiagnosisMetadataStore()
        artifact_store = InMemoryStructuredDiagnosisArtifactStore()
        for report_id in ["r1", "r2"]:
            metadata_store.put_metadata(metadata(report_id))
            artifact_store.write_report(
                s3_uri=f"s3://bucket/{report_id}.json",
                report=report(report_id),
        )
        existing_evidence = next(
            item
            for item in service_evidence_items(metadata_store, artifact_store)
            if item.evidence_id == "r1:q1"
        )
        existing_embedding_key = build_embedding_key(
            evidence_id="r1:q1",
            embedding_model="fake-embedding",
            embedding_input_version="v1",
        )
        embedding_store = RecordingEmbeddingStore(
            {
                ("s3://bucket/r1.json", existing_embedding_key): EvidenceEmbeddingRecord(
                    diagnosis_json_s3_uri="s3://bucket/r1.json",
                    embedding_key=existing_embedding_key,
                    evidence_id="r1:q1",
                    embedding_model="fake-embedding",
                    embedding_input_version="v1",
                    embedding_text_hash=embedding_text_hash(
                        build_embedding_input_text(
                            subject="Physics",
                            evidence=existing_evidence,
                        )
                    ),
                    embedding=[1.0, 0.0],
                    created_at="2026-07-18T00:00:00+00:00",
                )
            }
        )
        classifier = RecordingSemanticClassifier()
        service = StudentProfileApplicationService(
            metadata_store=metadata_store,
            artifact_store=artifact_store,
            semantic_analyzer=SemanticGapAnalyzer(
                embedding_service=EvidenceEmbeddingService(
                    store=embedding_store,
                    client=SingleVectorEmbeddingClient([[0.9, 0.1]]),
                ),
                classifier=classifier,
                similarity_threshold=0.95,
            ),
            report_service=ProfileAnalysisService(),
        )

        with patch(
            "jee_tutor.infrastructure.composition.build_student_profile_service",
            return_value=service,
        ):
            from jee_tutor.handler import handle_agentcore_request

            response = handle_agentcore_request(
                {
                    "task": "task profile",
                    "recipient_email": "student@example.com",
                    "subject": "Physics",
                }
            )

        self.assertEqual(response["profile_status"], "succeeded")
        self.assertIn("Physics Longitudinal Profile", response["profile_markdown"])
        self.assertEqual(len(embedding_store.puts), 1)
        self.assertEqual(embedding_store.puts[0].evidence_id, "r2:q1")
        self.assertEqual(classifier.candidates[0].evidence_ids, ["r1:q1", "r2:q1"])
        self.assertIn("Projectile components", response["profile_report"]["recurring_gaps"][0])

    def test_legacy_tutor_invocation_dispatches_profile_report_task(self):
        with patch("jee_tutor.infrastructure.composition.build_student_profile_service") as build_profile:
            build_profile.return_value.handle.return_value = {"profile_status": "no_history"}
            from jee_tutor.handler import handle_tutor_invocation

            response = handle_tutor_invocation(
                {
                    "task": "Profile",
                    "recipient_email": "student@example.com",
                    "subject": "Physics",
                }
            )

        self.assertEqual(response, {"profile_status": "no_history"})

    def test_agentcore_handler_dispatches_default_diagnosis_task(self):
        with patch("jee_tutor.infrastructure.composition.build_tutor_invocation_service") as build_tutor:
            build_tutor.return_value.handle.return_value = {"analysis": "ok"}
            from jee_tutor.handler import handle_agentcore_request

            response = handle_agentcore_request({"image_data_uri": "x"})

        self.assertEqual(response, {"analysis": "ok"})


class RecordingEmbeddingStore:
    def __init__(self, records):
        self.records = dict(records)
        self.puts = []

    def get_embedding(self, *, diagnosis_json_s3_uri: str, embedding_key: str):
        return self.records.get((diagnosis_json_s3_uri, embedding_key))

    def put_embedding(self, record) -> None:
        self.records[(record.diagnosis_json_s3_uri, record.embedding_key)] = record
        self.puts.append(record)


def service_evidence_items(metadata_store, artifact_store):
    from jee_tutor.profile.evidence import ProfileEvidenceLoader
    from jee_tutor.profile.models import ProfileReportRequest

    return ProfileEvidenceLoader(
        metadata_store=metadata_store,
        artifact_store=artifact_store,
    ).load(ProfileReportRequest(email="student@example.com", subject="Physics")).evidence_items


class SingleVectorEmbeddingClient:
    model = "fake-embedding"

    def __init__(self, vectors):
        self.vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.vectors


class RecordingSemanticClassifier:
    def __init__(self):
        self.candidates = []

    def classify(self, *, evidence_items, candidates):
        from jee_tutor.profile.semantic import SemanticGapCluster

        self.candidates = candidates
        return [
            SemanticGapCluster(
                cluster_id="semantic-cluster-1",
                cluster_type="same_underlying_gap",
                title="Projectile components",
                evidence_ids=["r1:q1", "r2:q1"],
                rationale="Mandatory classifier accepted the cosine candidate.",
            )
        ]


if __name__ == "__main__":
    unittest.main()
