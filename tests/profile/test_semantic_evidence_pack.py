import unittest

from jee_tutor.profile.evidence import ProfileEvidenceItem
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
from jee_tutor.profile.semantic import (
    LiteLLMSemanticClusterClassifier,
    SemanticCandidateCluster,
    SemanticClusterModelConfig,
    SemanticClusterModelSettings,
    SemanticGapAnalyzer,
    SemanticGapCluster,
    build_embedding_candidate_clusters,
    build_longitudinal_evidence_pack,
    cosine_similarity,
    semantic_cluster_response_format,
    validate_semantic_clusters,
)


def evidence(
    evidence_id: str,
    report_id: str,
    gap: str = "Projectile components",
    chapter: str = "Kinematics",
    topic: str = "Projectile motion",
) -> ProfileEvidenceItem:
    question_number = evidence_id.rsplit("q", 1)[-1]
    return ProfileEvidenceItem(
        evidence_id=evidence_id,
        evidence_reference=f"2026-07-18 : TEST_{report_id} : Q{question_number}",
        diagnosis_report_id=report_id,
        diagnosis_json_s3_uri=f"s3://bucket/{report_id}.json",
        subject="Physics",
        test_name=f"TEST_{report_id}",
        diagnosis_date="2026-07-18T10:00:00+00:00",
        question_number=question_number,
        chapter=chapter,
        topic=topic,
        exact_concept_gap=gap,
        likely_thought="You likely used constant speed.",
        why_wrong="Vertical acceleration changes velocity.",
        deep_dive_recommendation="Resolve horizontal and vertical motion.",
    )


class SemanticEvidencePackTest(unittest.TestCase):
    def test_embedding_record_rejects_non_numeric_vector_components(self):
        with self.assertRaisesRegex(ValueError, "valid number"):
            EvidenceEmbeddingRecord(
                diagnosis_json_s3_uri="s3://bucket/r1.json",
                embedding_key="r1:q1#fake-embedding#v1",
                evidence_id="r1:q1",
                embedding_model="fake-embedding",
                embedding_input_version="v1",
                embedding_text_hash="hash",
                embedding=["bad"],
                created_at="2026-07-18T00:00:00+00:00",
            )
        with self.assertRaisesRegex(ValueError, "Embedding components must be numeric"):
            EvidenceEmbeddingRecord.validate_embedding([object()])

    def test_cluster_validation_rejects_unknown_and_duplicate_evidence(self):
        items = [evidence("r1:q1", "r1")]

        with self.assertRaisesRegex(ValueError, "duplicate evidence ids"):
            SemanticGapCluster(
                cluster_id="bad",
                cluster_type="unrelated",
                title="bad",
                evidence_ids=["r1:q1", "r1:q1"],
                rationale="bad",
            )

        with self.assertRaisesRegex(ValueError, "duplicate evidence ids"):
            SemanticCandidateCluster(
                candidate_id="bad",
                evidence_ids=["r1:q1", "r1:q1"],
                rationale="bad",
            )

        with self.assertRaisesRegex(ValueError, "unknown evidence"):
            validate_semantic_clusters(
                [
                    SemanticGapCluster(
                        cluster_id="c1",
                        cluster_type="same_underlying_gap",
                        title="bad",
                        evidence_ids=["missing"],
                        rationale="bad",
                    )
                ],
                items,
            )

        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_semantic_clusters(
                [
                    SemanticGapCluster(
                        cluster_id="c1",
                        cluster_type="same_underlying_gap",
                        title="one",
                        evidence_ids=["r1:q1"],
                        rationale="one",
                    ),
                    SemanticGapCluster(
                        cluster_id="c2",
                        cluster_type="same_wrong_approach",
                        title="two",
                        evidence_ids=["r1:q1"],
                        rationale="two",
                    ),
                ],
                items,
            )

    def test_embedding_service_reuses_existing_and_creates_only_missing(self):
        items = [
            evidence("r1:q1", "r1", gap="Projectile components"),
            evidence("r2:q1", "r2", gap="Circular motion"),
        ]
        store = InMemoryEvidenceEmbeddingStore()
        existing_text = build_embedding_input_text(subject="Physics", evidence=items[0])
        store.put_embedding(
            EvidenceEmbeddingRecord(
                diagnosis_json_s3_uri="s3://bucket/r1.json",
                embedding_key=build_embedding_key(
                    evidence_id="r1:q1",
                    embedding_model="fake-embedding",
                    embedding_input_version="v1",
                ),
                evidence_id="r1:q1",
                embedding_model="fake-embedding",
                embedding_input_version="v1",
                embedding_text_hash=embedding_text_hash(existing_text),
                embedding=[1.0, 0.0],
                created_at="2026-07-18T00:00:00+00:00",
            )
        )
        client = FakeEmbeddingClient({"r2:q1": [0.0, 1.0]})

        records = EvidenceEmbeddingService(store=store, client=client).ensure_embeddings(
            subject="Physics",
            evidence_items=items,
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(len(client.last_texts), 1)
        self.assertEqual(records["r1:q1"].embedding, [1.0, 0.0])
        self.assertEqual(records["r2:q1"].embedding, [0.0, 1.0])

        client.calls = 0
        reused_records = EvidenceEmbeddingService(store=store, client=client).ensure_embeddings(
            subject="Physics",
            evidence_items=items,
        )

        self.assertEqual(client.calls, 0)
        self.assertEqual(sorted(reused_records), ["r1:q1", "r2:q1"])

    def test_embedding_service_recreates_stale_embeddings_and_checks_count(self):
        item = evidence("r1:q1", "r1")
        store = InMemoryEvidenceEmbeddingStore()
        store.put_embedding(
            EvidenceEmbeddingRecord(
                diagnosis_json_s3_uri="s3://bucket/r1.json",
                embedding_key=build_embedding_key(
                    evidence_id="r1:q1",
                    embedding_model="fake-embedding",
                    embedding_input_version="v1",
                ),
                evidence_id="r1:q1",
                embedding_model="fake-embedding",
                embedding_input_version="v1",
                embedding_text_hash="stale",
                embedding=[1.0, 0.0],
                created_at="2026-07-18T00:00:00+00:00",
            )
        )

        records = EvidenceEmbeddingService(
            store=store,
            client=SequentialEmbeddingClient([[0.0, 1.0]]),
        ).ensure_embeddings(subject="Physics", evidence_items=[item])

        self.assertEqual(records["r1:q1"].embedding, [0.0, 1.0])

        with self.assertRaisesRegex(ValueError, "unexpected number"):
            EvidenceEmbeddingService(
                store=InMemoryEvidenceEmbeddingStore(),
                client=SequentialEmbeddingClient([]),
            ).ensure_embeddings(subject="Physics", evidence_items=[item])

    def test_profile_embedding_config_and_litellm_client(self):
        settings = ProfileEmbeddingSettings(
            model="openai/text-embedding-3-small",
            dimensions=128,
            api_key="key",
            api_base="https://proxy.example",
        )
        self.assertEqual(
            settings.to_litellm_kwargs(),
            {
                "model": "openai/text-embedding-3-small",
                "dimensions": 128,
                "api_key": "key",
                "api_base": "https://proxy.example",
            },
        )
        self.assertEqual(
            ProfileEmbeddingSettings(model="fake-embedding").to_litellm_kwargs(),
            {"model": "fake-embedding"},
        )
        config = ProfileEmbeddingConfig(
            environ={
                "PROFILE_EMBEDDING_MODEL": "gemini/text-embedding-004",
                "PROFILE_EMBEDDING_DIMENSIONS": "64",
                "GOOGLE_API_KEY": "google-key",
                "LITELLM_BASE_URL": "https://proxy.example",
            },
            config={},
        )
        resolved = config.resolve()
        self.assertEqual(resolved.model, "gemini/text-embedding-004")
        self.assertEqual(resolved.dimensions, 64)
        self.assertEqual(resolved.api_key, "google-key")

        openai_resolved = ProfileEmbeddingConfig(
            environ={
                "PROFILE_EMBEDDING_MODEL": "openai/text-embedding-3-small",
                "OPENAI_API_KEY": "openai-key",
            },
            config={"profile_embedding": {"dimensions": None}},
        ).resolve()
        self.assertEqual(openai_resolved.api_key, "openai-key")

        captured = {}

        def embedding_fn(**kwargs):
            captured.update(kwargs)
            return {"data": [{"embedding": [1, 2]}]}

        client = LiteLLMEvidenceEmbeddingClient(config=config, embedding_fn=embedding_fn)
        self.assertEqual(client.embed([]), [])
        self.assertEqual(client.model, "gemini/text-embedding-004")
        self.assertEqual(client.embed(["text"]), [[1.0, 2.0]])
        self.assertEqual(captured["input"], ["text"])

        fallback = ProfileEmbeddingConfig(
            environ={"PROFILE_EMBEDDING_MODEL": "custom/model", "LITELLM_API_KEY": "key"},
            config={"profile_embedding": "bad"},
        ).resolve()
        self.assertEqual(fallback.api_key, "key")

        default = ProfileEmbeddingConfig(environ={}, config={}).resolve()
        self.assertEqual(default.model, "gemini/gemini-embedding-2")
        self.assertEqual(default.dimensions, 256)

    def test_cosine_similarity_candidates_are_scoped_to_requested_evidence(self):
        items = [
            evidence("r1:q1", "r1", gap="Projectile components"),
            evidence("r2:q1", "r2", gap="Resolving velocity into components"),
            evidence("r3:q1", "r3", gap="Circular motion"),
        ]
        records = {
            "r1:q1": embedding_record("r1:q1", "s3://bucket/r1.json", [1.0, 0.0]),
            "r2:q1": embedding_record("r2:q1", "s3://bucket/r2.json", [0.9, 0.1]),
            "r3:q1": embedding_record("r3:q1", "s3://bucket/r3.json", [0.0, 1.0]),
        }

        candidates = build_embedding_candidate_clusters(
            evidence_items=items,
            embedding_records=records,
            similarity_threshold=0.95,
        )

        self.assertEqual([candidate.evidence_ids for candidate in candidates], [
            ["r1:q1", "r2:q1"],
            ["r3:q1"],
        ])

        normalized_candidates = build_embedding_candidate_clusters(
            evidence_items=[
                evidence("r4:q1", "r4", gap="Projectile components"),
                evidence("r5:q1", "r5", gap="projectile-components!"),
            ],
            embedding_records={
                "r4:q1": embedding_record("r4:q1", "s3://bucket/r4.json", [1.0, 0.0]),
                "r5:q1": embedding_record("r5:q1", "s3://bucket/r5.json", [0.0, 1.0]),
            },
            similarity_threshold=0.99,
        )
        self.assertEqual(normalized_candidates[0].evidence_ids, ["r4:q1", "r5:q1"])

        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 0.0]), 0.0)
        with self.assertRaisesRegex(ValueError, "same dimensions"):
            cosine_similarity([1.0], [1.0, 0.0])
        with self.assertRaisesRegex(ValueError, "Missing embeddings"):
            build_embedding_candidate_clusters(
                evidence_items=items,
                embedding_records={},
            )

    def test_semantic_analyzer_uses_mandatory_classifier_for_final_clusters(self):
        items = [
            evidence("r1:q1", "r1", gap="Projectile components"),
            evidence("r2:q1", "r2", gap="Resolving velocity into components"),
        ]
        embedding_service = FakeEmbeddingService(
            {
                "r1:q1": [1.0, 0.0],
                "r2:q1": [0.9, 0.1],
            }
        )
        classifier = FakeClassifier(
            [
                SemanticGapCluster(
                    cluster_id="llm-cluster",
                    cluster_type="same_underlying_gap",
                    title="Projectile components",
                    evidence_ids=["r1:q1", "r2:q1"],
                    rationale="LLM classified the embedding candidate as the same gap.",
                )
            ]
        )

        clusters = SemanticGapAnalyzer(
            embedding_service=embedding_service,
            classifier=classifier,
            similarity_threshold=0.95,
        ).cluster(items, subject="Physics")

        self.assertEqual([cluster.cluster_id for cluster in clusters], ["llm-cluster"])
        self.assertEqual(classifier.seen_candidates[0].evidence_ids, ["r1:q1", "r2:q1"])

    def test_semantic_analyzer_rejects_mixed_subject_default_scope(self):
        items = [
            evidence("r1:q1", "r1"),
            evidence("r2:q1", "r2"),
        ]
        items[1] = items[1].model_copy(update={"subject": "Maths"})

        with self.assertRaisesRegex(ValueError, "one subject"):
            SemanticGapAnalyzer(
                embedding_service=FakeEmbeddingService({}),
                classifier=FakeClassifier([]),
            ).cluster(items)

    def test_litellm_semantic_classifier_parses_structured_output(self):
        item = evidence("r1:q1", "r1")
        candidate = SemanticCandidateCluster(
            candidate_id="candidate-1",
            evidence_ids=["r1:q1"],
            rationale="single candidate",
        )
        captured = {}

        def completion_fn(**kwargs):
            captured.update(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"clusters":[{"cluster_id":"c1","cluster_type":"unrelated",'
                                '"title":"Projectile components","evidence_ids":["r1:q1"],'
                                '"rationale":"single item"}]}'
                            )
                        }
                    }
                ]
            }

        classifier = LiteLLMSemanticClusterClassifier(
            model_config=FakeSemanticClusterModelConfig(),
            completion_fn=completion_fn,
        )
        clusters = classifier.classify(evidence_items=[item], candidates=[candidate])

        self.assertEqual(clusters[0].cluster_id, "c1")
        self.assertEqual(captured["model"], "fake/semantic")
        self.assertEqual(captured["num_retries"], 0)
        self.assertEqual(captured["response_format"]["json_schema"]["name"], "student_profile_semantic_clusters")
        self.assertIn("candidate_clusters", captured["messages"][1]["content"])

    def test_semantic_cluster_model_config_resolves_env_and_dict_config(self):
        settings = SemanticClusterModelSettings(
            model="openai/gpt-4o",
            api_key="key",
            api_base="https://proxy.example",
            completion_options={"timeout": 3},
        )
        self.assertEqual(settings.to_litellm_kwargs()["api_key"], "key")

        config = SemanticClusterModelConfig(
            environ={
                "PROFILE_SEMANTIC_CLUSTER_MODEL": "gemini/gemini-2.5-pro",
                "GOOGLE_API_KEY": "google-key",
                "LITELLM_BASE_URL": "https://proxy.example",
            },
            config={"completion": {"timeout": 7}},
        )
        resolved = config.resolve()
        self.assertEqual(resolved.model, "gemini/gemini-2.5-pro")
        self.assertEqual(resolved.api_key, "google-key")
        self.assertEqual(resolved.completion_options["timeout"], 7)
        self.assertEqual(semantic_cluster_response_format()["json_schema"]["strict"], True)

        fallback = SemanticClusterModelConfig(
            environ={
                "PROFILE_SEMANTIC_CLUSTER_MODEL": "custom/model",
                "LITELLM_API_KEY": "litellm-key",
            },
            config={"completion": "bad"},
        ).resolve()
        self.assertEqual(fallback.api_key, "litellm-key")

    def test_evidence_pack_marks_recurrence_only_across_reports(self):
        items = [
            evidence("r1:q1", "r1"),
            evidence("r1:q2", "r1"),
            evidence("r2:q1", "r2"),
            evidence("r3:q1", "r3", gap="Circular motion"),
        ]
        clusters = [
            SemanticGapCluster(
                cluster_id="recurring",
                cluster_type="same_underlying_gap",
                title="Projectile components",
                evidence_ids=["r1:q1", "r1:q2", "r2:q1"],
                rationale="same gap",
            ),
            SemanticGapCluster(
                cluster_id="isolated",
                cluster_type="same_underlying_gap",
                title="Circular motion",
                evidence_ids=["r3:q1"],
                rationale="single report",
            ),
        ]

        pack = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=items,
            clusters=clusters,
        )

        by_id = {cluster.cluster.cluster_id: cluster for cluster in pack.clusters}
        self.assertEqual(by_id["recurring"].recurrence_label, "recurring")
        self.assertEqual(by_id["recurring"].diagnosis_report_count, 2)
        self.assertEqual(
            by_id["isolated"].recurrence_label,
            "isolated_or_early_indicator",
        )
        self.assertEqual(pack.diagnosis_report_count, 3)
        self.assertEqual(pack.question_count, 4)
        self.assertIn("r1:q1", pack.evidence_index)
        self.assertEqual(pack.chapter_topic_map[0].chapter, "Kinematics")

    def test_evidence_pack_serializes_without_losing_references(self):
        item = evidence("r1:q1", "r1")
        clusters = SemanticGapAnalyzer(
            clusterer=lambda _items: [
                SemanticGapCluster(
                    cluster_id="cluster-1",
                    cluster_type="unrelated",
                    title="Projectile components",
                    evidence_ids=["r1:q1"],
                    rationale="single evidence item",
                )
            ]
        ).cluster([item])

        payload = build_longitudinal_evidence_pack(
            subject="Physics",
            evidence_items=[item],
            clusters=clusters,
        ).model_dump()

        self.assertEqual(payload["evidence_index"]["r1:q1"]["diagnosis_report_id"], "r1")
        self.assertEqual(payload["clusters"][0]["question_count"], 1)

class FakeEmbeddingClient:
    model = "fake-embedding"

    def __init__(self, vectors_by_evidence_id: dict[str, list[float]]):
        self.vectors_by_evidence_id = vectors_by_evidence_id
        self.calls = 0
        self.last_texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.last_texts = texts
        vectors: list[list[float]] = []
        for text in texts:
            matched_id = next(
                evidence_id
                for evidence_id in self.vectors_by_evidence_id
                if evidence_id.split(":", 1)[0] in text
                or self.vectors_by_evidence_id[evidence_id] not in vectors
            )
            vectors.append(self.vectors_by_evidence_id[matched_id])
        return vectors


class SequentialEmbeddingClient:
    model = "fake-embedding"

    def __init__(self, vectors: list[list[float]]):
        self.vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.vectors


class FakeEmbeddingService:
    def __init__(self, vectors_by_evidence_id: dict[str, list[float]]):
        self.vectors_by_evidence_id = vectors_by_evidence_id

    def ensure_embeddings(
        self,
        *,
        subject: str,
        evidence_items: list[ProfileEvidenceItem],
    ) -> dict[str, EvidenceEmbeddingRecord]:
        return {
            item.evidence_id: embedding_record(
                item.evidence_id,
                item.diagnosis_json_s3_uri,
                self.vectors_by_evidence_id[item.evidence_id],
            )
            for item in evidence_items
        }


class FakeClassifier:
    def __init__(self, clusters: list[SemanticGapCluster]):
        self.clusters = clusters
        self.seen_candidates: list[SemanticCandidateCluster] = []

    def classify(
        self,
        *,
        evidence_items: list[ProfileEvidenceItem],
        candidates: list[SemanticCandidateCluster],
    ) -> list[SemanticGapCluster]:
        self.seen_candidates = candidates
        return self.clusters


class FakeSemanticClusterModelConfig:
    def resolve(self):
        return SemanticClusterModelSettings(
            model="fake/semantic",
            completion_options={},
        )


def embedding_record(
    evidence_id: str,
    diagnosis_json_s3_uri: str,
    vector: list[float],
) -> EvidenceEmbeddingRecord:
    return EvidenceEmbeddingRecord(
        diagnosis_json_s3_uri=diagnosis_json_s3_uri,
        embedding_key=build_embedding_key(
            evidence_id=evidence_id,
            embedding_model="fake-embedding",
            embedding_input_version="v1",
        ),
        evidence_id=evidence_id,
        embedding_model="fake-embedding",
        embedding_input_version="v1",
        embedding_text_hash="hash",
        embedding=vector,
        created_at="2026-07-18T00:00:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
