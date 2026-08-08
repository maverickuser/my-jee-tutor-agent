import unittest
from contextlib import contextmanager

from jee_tutor.profile.embeddings import (
    EvidenceEmbeddingRecord,
    EvidenceEmbeddingService,
    InMemoryEvidenceEmbeddingStore,
    LiteLLMEvidenceEmbeddingClient,
    ProfileEmbeddingConfig,
    ProfileEmbeddingSettings,
    build_embedding_input_text,
    build_embedding_key,
    embedding_text_hash,
)
from tests.profile.test_hierarchical_profile import evidence


class EvidenceEmbeddingTest(unittest.TestCase):
    def test_embedding_input_contains_only_diagnosis_fields(self):
        item = evidence("r1", "q1")
        text = build_embedding_input_text(evidence=item)
        self.assertIn("Exact concept gap: Projectile components", text)
        self.assertIn("Likely student thought:", text)
        self.assertIn("Why wrong:", text)
        self.assertNotIn(item.chapter, text)
        self.assertNotIn(item.deep_dive_recommendation, text)

    def test_record_rejects_invalid_vector(self):
        with self.assertRaisesRegex(ValueError, "valid number"):
            embedding_record("r1:q1", ["bad"])
        with self.assertRaisesRegex(ValueError, "numeric"):
            EvidenceEmbeddingRecord.validate_embedding([object()])

    def test_service_reuses_current_record_and_creates_missing_record(self):
        items = [evidence("r1", "q1"), evidence("r2", "q1")]
        store = InMemoryEvidenceEmbeddingStore()
        text = build_embedding_input_text(evidence=items[0])
        store.put_embedding(
            embedding_record(
                items[0].evidence_id,
                [1.0, 0.0],
                text_hash=embedding_text_hash(text),
            )
        )
        client = SequentialEmbeddingClient([[0.0, 1.0]])

        records = EvidenceEmbeddingService(store=store, client=client).ensure_embeddings(
            subject="Physics", evidence_items=items
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(records[items[0].evidence_id].embedding, [1.0, 0.0])
        self.assertEqual(records[items[1].evidence_id].embedding, [0.0, 1.0])

    def test_service_replaces_stale_record_and_validates_result_count(self):
        item = evidence("r1", "q1")
        store = InMemoryEvidenceEmbeddingStore()
        store.put_embedding(embedding_record(item.evidence_id, [1.0, 0.0], text_hash="stale"))
        records = EvidenceEmbeddingService(
            store=store, client=SequentialEmbeddingClient([[0.0, 1.0]])
        ).ensure_embeddings(subject="Physics", evidence_items=[item])
        self.assertEqual(records[item.evidence_id].embedding, [0.0, 1.0])

        with self.assertRaisesRegex(ValueError, "unexpected number"):
            EvidenceEmbeddingService(
                store=InMemoryEvidenceEmbeddingStore(),
                client=SequentialEmbeddingClient([]),
            ).ensure_embeddings(subject="Physics", evidence_items=[item])

    def test_embedding_configuration_and_client(self):
        settings = ProfileEmbeddingSettings(
            model="openai/text-embedding-3-small",
            dimensions=128,
            api_key="key",
            api_base="https://proxy.example",
        )
        self.assertEqual(settings.to_litellm_kwargs()["dimensions"], 128)
        config = ProfileEmbeddingConfig(
            environ={
                "PROFILE_EMBEDDING_MODEL": "gemini/text-embedding-004",
                "PROFILE_EMBEDDING_DIMENSIONS": "64",
                "GOOGLE_API_KEY": "google-key",
            },
            config={},
        )
        resolved = config.resolve()
        self.assertEqual(resolved.dimensions, 64)
        self.assertEqual(resolved.api_key, "google-key")

        captured = {}

        def embedding_fn(**kwargs):
            captured.update(kwargs)
            return {"data": [{"embedding": [1, 2]}]}

        client = LiteLLMEvidenceEmbeddingClient(config=config, embedding_fn=embedding_fn)
        self.assertEqual(client.embed([]), [])
        self.assertEqual(client.embed(["text"]), [[1.0, 2.0]])
        self.assertEqual(captured["input"], ["text"])

    def test_each_embedding_batch_has_one_observation_with_usage_and_cost(self):
        observability = RecordingEmbeddingObservability()
        client = LiteLLMEvidenceEmbeddingClient(
            config=ProfileEmbeddingConfig(
                environ={
                    "PROFILE_EMBEDDING_MODEL": "gemini/gemini-embedding-001",
                    "GOOGLE_API_KEY": "key",
                },
                config={},
            ),
            observability=observability,
            embedding_fn=lambda **_kwargs: {
                "data": [{"embedding": [1.0]}],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
                "_hidden_params": {"response_cost": 0.001},
            },
        )

        self.assertEqual(client.embed(["text"]), [[1.0]])
        self.assertEqual(len(observability.spans), 1)
        self.assertEqual(observability.spans[0]["metadata"]["attempt"], 1)
        self.assertEqual(
            observability.updates[0]["usage_details"],
            {"input": 4, "total": 4},
        )
        self.assertEqual(observability.updates[0]["cost_details"], {"total": 0.001})


class SequentialEmbeddingClient:
    model = "fake-embedding"

    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = 0

    def embed(self, _texts):
        self.calls += 1
        return self.vectors


class RecordingEmbeddingObservability:
    def __init__(self):
        self.spans = []
        self.updates = []

    @contextmanager
    def embedding_span(self, **kwargs):
        self.spans.append(kwargs)
        observation = MockEmbeddingObservation(self.updates)
        yield observation


class MockEmbeddingObservation:
    def __init__(self, updates):
        self.updates = updates

    def update(self, **kwargs):
        self.updates.append(kwargs)


def embedding_record(evidence_id, vector, *, text_hash="hash"):
    return EvidenceEmbeddingRecord(
        diagnosis_json_s3_uri=f"s3://bucket/{evidence_id.split(':')[0]}.json",
        embedding_key=build_embedding_key(
            evidence_id=evidence_id,
            embedding_model="fake-embedding",
            embedding_input_version="v2",
        ),
        evidence_id=evidence_id,
        embedding_model="fake-embedding",
        embedding_input_version="v2",
        embedding_text_hash=text_hash,
        embedding=vector,
        created_at="2026-01-01T00:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
