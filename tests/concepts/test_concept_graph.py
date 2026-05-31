import json
import unittest
from unittest.mock import Mock, patch

from jee_tutor.concepts.graph import (
    ConceptGraphMatch,
    ConceptGraphSettings,
    DynamoDBConceptGraphRetriever,
)
from jee_tutor.concepts.grounding import ConceptGraphGrounder
from jee_tutor.concepts.tool import ConceptGraphTool, build_concept_graph_tool


class FakeDynamoDBClient:
    def __init__(self, *, query_items=None, get_items=None, batch_get_responses=None):
        self.query_items = query_items or {}
        self.get_items = get_items or {}
        self.batch_get_responses = list(batch_get_responses or [])
        self.queries = []
        self.gets = []
        self.batch_gets = []

    def get_item(self, **kwargs):
        self.gets.append(kwargs)
        key = (kwargs["Key"]["PK"]["S"], kwargs["Key"]["SK"]["S"])
        item = self.get_items.get(key)
        return {"Item": item} if item else {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        values = kwargs["ExpressionAttributeValues"]
        key = (values[":pk"]["S"], values[":sk"]["S"])
        return {"Items": self.query_items.get(key, [])}

    def batch_get_item(self, **kwargs):
        self.batch_gets.append(kwargs)
        if self.batch_get_responses:
            return self.batch_get_responses.pop(0)
        responses = []
        for table_request in kwargs["RequestItems"].values():
            for key in table_request["Keys"]:
                item_key = (key["PK"]["S"], key["SK"]["S"])
                if item := self.get_items.get(item_key):
                    responses.append(item)
        return {"Responses": {"concepts": responses}}


def _settings():
    return ConceptGraphSettings(enabled=True, table_name="concepts", max_depth=2)


class ConceptGraphTest(unittest.TestCase):
    def test_settings_from_env_parses_runtime_configuration(self):
        settings = ConceptGraphSettings.from_env(
            {
                "CONCEPT_GRAPH_ENABLED": "true",
                "CONCEPT_GRAPH_TABLE_NAME": "jee-concepts",
                "CONCEPT_GRAPH_REGION": "ap-south-1",
                "CONCEPT_GRAPH_ENDPOINT_URL": "http://localhost:8000",
                "CONCEPT_GRAPH_DEFAULT_SUBJECT": "Physics",
                "CONCEPT_GRAPH_MAX_DEPTH": "3",
                "CONCEPT_GRAPH_MAX_RESULTS": "7",
            }
        )

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.table_name, "jee-concepts")
        self.assertEqual(settings.region_name, "ap-south-1")
        self.assertEqual(settings.endpoint_url, "http://localhost:8000")
        self.assertEqual(settings.default_subject, "Physics")
        self.assertEqual(settings.max_depth, 3)
        self.assertEqual(settings.max_results, 7)

    def test_settings_from_env_falls_back_on_invalid_ints(self):
        settings = ConceptGraphSettings.from_env(
            {
                "CONCEPT_GRAPH_MAX_DEPTH": "not-a-number",
                "CONCEPT_GRAPH_MAX_RESULTS": "bad",
            }
        )

        self.assertEqual(settings.max_depth, 2)
        self.assertEqual(settings.max_results, 5)

    def test_settings_from_env_clamps_unsafe_ints(self):
        settings = ConceptGraphSettings.from_env(
            {
                "CONCEPT_GRAPH_MAX_DEPTH": "0",
                "CONCEPT_GRAPH_MAX_RESULTS": "100",
            }
        )

        self.assertEqual(settings.max_depth, 2)
        self.assertEqual(settings.max_results, 5)

    def test_disabled_graph_returns_disabled_match_without_aws_call(self):
        retriever = DynamoDBConceptGraphRetriever(
            ConceptGraphSettings(enabled=False, table_name=None),
            dynamodb_client=FakeDynamoDBClient(),
        )

        match = retriever.validate(subject="physics", topic="kinematics")

        self.assertFalse(match.matched)
        self.assertEqual(match.confidence, "disabled")

    def test_chapter_topic_lookup_fetches_active_version_metadata_and_prereqs(self):
        client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"graph_version": "v7"},
                (
                    "GRAPH#physics#VERSION#v7#CONCEPT#physics.motion.velocity",
                    "META",
                ): {
                    "chapter": "Motion In A Straight Line",
                    "topic": "Velocity",
                    "name": "Average Velocity",
                    "testable_skill": "Distinguish displacement/time from distance/time",
                    "common_confusions": ["speed vs velocity"],
                },
            },
            query_items={
                (
                    "GRAPH#physics#VERSION#v7#CHAPTER#motion_in_a_straight_line",
                    "TOPIC#velocity#CONCEPT#",
                ): [{"SK": "TOPIC#velocity#CONCEPT#physics.motion.velocity"}],
                (
                    "GRAPH#physics#VERSION#v7#CONCEPT#physics.motion.velocity",
                    "PREREQ#D1#",
                ): [
                    {
                        "SK": "PREREQ#D1#source_order#physics.units.dimensions",
                        "quality": "source_order",
                        "name": "Units and dimensions",
                    },
                    {
                        "SK": "PREREQ#D1#reviewed#physics.vectors",
                        "quality": "reviewed",
                        "name": "Vectors",
                    },
                ],
            },
        )
        retriever = DynamoDBConceptGraphRetriever(_settings(), dynamodb_client=client)

        match = retriever.validate(
            subject="physics",
            chapter="Motion in a Straight Line",
            topic="Velocity",
            microconcept="avg velocity",
        )

        self.assertTrue(match.matched)
        self.assertEqual(match.concept_id, "physics.motion.velocity")
        self.assertEqual(match.canonical_topic, "Velocity")
        self.assertEqual(match.prerequisites[0]["name"], "Vectors")
        self.assertIn("speed vs velocity", match.common_confusions)

    def test_chapter_topic_lookup_ranks_candidates_by_microconcept_overlap(self):
        client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"graph_version": "v1"},
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.motion.speed", "META"): {
                    "chapter": "Motion",
                    "topic": "Velocity",
                    "name": "Speed",
                },
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.motion.average_velocity", "META"): {
                    "chapter": "Motion",
                    "topic": "Velocity",
                    "name": "Average Velocity",
                    "aliases": ["mean velocity"],
                },
            },
            query_items={
                ("GRAPH#physics#VERSION#v1#CHAPTER#motion", "TOPIC#velocity#CONCEPT#"): [
                    {"SK": "TOPIC#velocity#CONCEPT#physics.motion.speed"},
                    {"SK": "TOPIC#velocity#CONCEPT#physics.motion.average_velocity"},
                ],
            },
        )
        retriever = DynamoDBConceptGraphRetriever(_settings(), dynamodb_client=client)

        match = retriever.validate(
            subject="physics",
            chapter="Motion",
            topic="Velocity",
            microconcept="average velocity",
        )

        self.assertEqual(match.concept_id, "physics.motion.average_velocity")

    def test_candidate_ranking_preserves_index_order_when_scores_tie(self):
        client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"graph_version": "v1"},
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.first", "META"): {
                    "chapter": "Motion",
                    "topic": "Velocity",
                    "name": "First Candidate",
                },
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.second", "META"): {
                    "chapter": "Motion",
                    "topic": "Velocity",
                    "name": "Second Candidate",
                },
            },
            query_items={
                ("GRAPH#physics#VERSION#v1#CHAPTER#motion", "TOPIC#velocity#CONCEPT#"): [
                    {"SK": "TOPIC#velocity#CONCEPT#physics.first"},
                    {"SK": "TOPIC#velocity#CONCEPT#physics.second"},
                ],
            },
        )
        retriever = DynamoDBConceptGraphRetriever(_settings(), dynamodb_client=client)

        match = retriever.validate(subject="physics", chapter="Motion", topic="Velocity")

        self.assertEqual(match.concept_id, "physics.first")

    def test_candidate_ranking_prefers_candidate_with_metadata_on_tie(self):
        client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"graph_version": "v1"},
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.second", "META"): {
                    "chapter": "Motion",
                    "topic": "Velocity",
                    "name": "Velocity",
                },
            },
            query_items={
                ("GRAPH#physics#VERSION#v1#CHAPTER#motion", "TOPIC#velocity#CONCEPT#"): [
                    {"SK": "TOPIC#velocity#CONCEPT#physics.first"},
                    {"SK": "TOPIC#velocity#CONCEPT#physics.second"},
                ],
            },
        )
        retriever = DynamoDBConceptGraphRetriever(_settings(), dynamodb_client=client)

        match = retriever.validate(subject="physics", chapter="Motion", topic="Velocity")

        self.assertTrue(match.matched)
        self.assertEqual(match.concept_id, "physics.second")

    def test_specific_query_with_zero_relevance_returns_low_confidence_match(self):
        client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"graph_version": "v1"},
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.motion.speed", "META"): {
                    "chapter": "Motion",
                    "topic": "Speed",
                    "name": "Speed",
                },
            },
            query_items={
                ("GRAPH#physics#VERSION#v1#CHAPTER#motion", "TOPIC#speed#CONCEPT#"): [
                    {"SK": "TOPIC#speed#CONCEPT#physics.motion.speed"},
                ],
            },
        )
        retriever = DynamoDBConceptGraphRetriever(_settings(), dynamodb_client=client)

        match = retriever.validate(
            subject="physics",
            chapter="Motion",
            topic="Speed",
            microconcept="electric flux gaussian surface",
            concept_gap="electric flux gaussian surface",
        )

        self.assertTrue(match.matched)
        self.assertEqual(match.confidence, "low")
        self.assertTrue(
            any("specific diagnosis terms" in note for note in match.validation_notes)
        )

    def test_term_index_fallback_handles_no_chapter_topic_match(self):
        client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"graph_version": "v1"},
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.work.energy", "META"): {
                    "chapter": "Work Energy Power",
                    "topic": "Work",
                    "micro_concept": "Work Done By Constant Force",
                },
            },
            query_items={
                (
                    "GRAPH#physics#VERSION#v1#TERM#work",
                    "CONCEPT#",
                ): [{"concept_id": "physics.work.energy"}],
            },
        )
        retriever = DynamoDBConceptGraphRetriever(_settings(), dynamodb_client=client)

        match = retriever.validate(subject="physics", concept_gap="work energy theorem")

        self.assertTrue(match.matched)
        self.assertEqual(match.canonical_chapter, "Work Energy Power")

    def test_prerequisite_edges_are_enriched_from_concept_metadata(self):
        client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"graph_version": "v1"},
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.motion.velocity", "META"): {
                    "chapter": "Motion",
                    "topic": "Velocity",
                    "name": "Velocity",
                },
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.vectors", "META"): {
                    "PK": "GRAPH#physics#VERSION#v1#CONCEPT#physics.vectors",
                    "SK": "META",
                    "chapter": "Mathematical Tools",
                    "topic": "Vectors",
                    "name": "Vector Addition",
                },
            },
            query_items={
                ("GRAPH#physics#VERSION#v1#TERM#velocity", "CONCEPT#"): [
                    {"concept_id": "physics.motion.velocity"}
                ],
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.motion.velocity", "PREREQ#D1#"): [
                    {"SK": "PREREQ#D1#reviewed#physics.vectors", "quality": "reviewed"}
                ],
            },
        )
        retriever = DynamoDBConceptGraphRetriever(_settings(), dynamodb_client=client)

        match = retriever.validate(subject="physics", concept_gap="velocity")

        self.assertEqual(match.prerequisites[0]["prerequisite_id"], "physics.vectors")
        self.assertEqual(match.prerequisites[0]["name"], "Vector Addition")
        self.assertIn("Vector Addition", match.deep_dive)

    def test_prerequisite_enrichment_retries_unprocessed_batch_get_keys(self):
        key = {
            "PK": {"S": "GRAPH#physics#VERSION#v1#CONCEPT#physics.vectors"},
            "SK": {"S": "META"},
        }
        client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"graph_version": "v1"},
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.motion.velocity", "META"): {
                    "chapter": "Motion",
                    "topic": "Velocity",
                    "name": "Velocity",
                },
            },
            query_items={
                ("GRAPH#physics#VERSION#v1#TERM#velocity", "CONCEPT#"): [
                    {"concept_id": "physics.motion.velocity"}
                ],
                ("GRAPH#physics#VERSION#v1#CONCEPT#physics.motion.velocity", "PREREQ#D1#"): [
                    {"SK": "PREREQ#D1#reviewed#physics.vectors", "quality": "reviewed"}
                ],
            },
            batch_get_responses=[
                {
                    "Responses": {"concepts": []},
                    "UnprocessedKeys": {"concepts": {"Keys": [key]}},
                },
                {
                    "Responses": {
                        "concepts": [
                            {
                                "PK": "GRAPH#physics#VERSION#v1#CONCEPT#physics.vectors",
                                "SK": "META",
                                "name": "Vector Addition",
                            }
                        ]
                    }
                },
            ],
        )
        sleep = Mock()
        retriever = DynamoDBConceptGraphRetriever(
            _settings(),
            dynamodb_client=client,
            sleep_fn=sleep,
        )

        match = retriever.validate(subject="physics", concept_gap="velocity")

        self.assertEqual(len(client.batch_gets), 2)
        sleep.assert_called_once_with(0.05)
        self.assertEqual(match.prerequisites[0]["name"], "Vector Addition")

    def test_term_index_fallback_can_parse_concept_id_from_sort_key(self):
        client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"version": "v2"},
                ("GRAPH#physics#VERSION#v2#CONCEPT#physics.rotation.torque", "META"): {
                    "chapter": "Rotational Motion",
                    "topic": "Torque",
                    "name": "Torque",
                },
            },
            query_items={
                (
                    "GRAPH#physics#VERSION#v2#TERM#torque",
                    "CONCEPT#",
                ): [{"SK": "CONCEPT#physics.rotation.torque"}],
            },
        )
        retriever = DynamoDBConceptGraphRetriever(_settings(), dynamodb_client=client)

        match = retriever.validate(subject="physics", concept_gap="torque direction")

        self.assertTrue(match.matched)
        self.assertEqual(match.concept_id, "physics.rotation.torque")

    def test_no_match_and_missing_metadata_are_reported_without_crashing(self):
        no_match = DynamoDBConceptGraphRetriever(
            _settings(),
            dynamodb_client=FakeDynamoDBClient(
                get_items={("GRAPH#physics", "ACTIVE"): {"graph_version": "v1"}}
            ),
        ).validate(subject="physics", concept_gap="xy")

        self.assertFalse(no_match.matched)
        self.assertIn("No matching concept", no_match.validation_notes[0])

        missing_meta = DynamoDBConceptGraphRetriever(
            _settings(),
            dynamodb_client=FakeDynamoDBClient(
                get_items={("GRAPH#physics", "ACTIVE"): {"graph_version": "v1"}},
                query_items={
                    ("GRAPH#physics#VERSION#v1#TERM#current", "CONCEPT#"): [
                        {"concept_id": "physics.current"}
                    ]
                },
            ),
        ).validate(subject="physics", concept_gap="current electricity")

        self.assertFalse(missing_meta.matched)
        self.assertEqual(missing_meta.concept_id, "physics.current")
        self.assertEqual(missing_meta.confidence, "low")

    def test_missing_active_graph_version_returns_controlled_no_match(self):
        client = FakeDynamoDBClient()
        match = DynamoDBConceptGraphRetriever(
            _settings(),
            dynamodb_client=client,
        ).validate(subject="physics", concept_gap="current electricity")

        self.assertFalse(match.matched)
        self.assertIn("Active concept graph version", match.validation_notes[0])
        self.assertEqual(len(client.queries), 0)

    def test_deserializes_dynamodb_attribute_values_and_creates_client_lazily(self):
        created_client = FakeDynamoDBClient(
            get_items={
                ("GRAPH#physics", "ACTIVE"): {"graph_version": {"S": "v1"}},
            }
        )
        retriever = DynamoDBConceptGraphRetriever(_settings())

        with patch("jee_tutor.concepts.graph.boto3.client", return_value=created_client) as client:
            match = retriever.validate(subject="Physics", concept_gap="current")

        client.assert_called_once_with(
            "dynamodb",
            region_name=None,
            endpoint_url=None,
        )
        self.assertFalse(match.matched)

    def test_concept_graph_tool_returns_json_validation(self):
        class Retriever:
            def validate(self, **kwargs):
                return type(
                    "Match",
                    (),
                    {"model_dump": lambda self: {"matched": True, "concept_id": "c1"}},
                )()

        payload = ConceptGraphTool(retriever=Retriever())._run(topic="vectors")

        self.assertEqual(json.loads(payload), {"concept_id": "c1", "matched": True})

    def test_concept_graph_tool_returns_structured_error_on_retriever_failure(self):
        class Retriever:
            def validate(self, **kwargs):
                raise RuntimeError("dynamo throttled")

        payload = json.loads(ConceptGraphTool(retriever=Retriever())._run(topic="vectors"))

        self.assertFalse(payload["matched"])
        self.assertEqual(payload["confidence"], "error")
        self.assertIn("dynamo throttled", payload["error"])

    def test_build_concept_graph_tool_defaults_to_dynamodb_retriever(self):
        with patch("jee_tutor.concepts.tool.DynamoDBConceptGraphRetriever") as retriever:
            tool = build_concept_graph_tool()

        retriever.assert_called_once()
        self.assertIs(tool.retriever, retriever.return_value)

    def test_grounding_updates_table_with_canonical_graph_terms(self):
        class Retriever:
            def validate(self, **kwargs):
                return ConceptGraphMatch(
                    matched=True,
                    confidence="high",
                    concept_id="physics.motion.velocity",
                    canonical_chapter="Motion In A Straight Line",
                    canonical_topic="Velocity",
                    canonical_microconcept="Average Velocity",
                    deep_dive=["Displacement", "Vectors"],
                )

        analysis = (
            "| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | "
            "Exact Concept Gap | What You Must Deep-Dive |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| Q1 | Motion | Speed | Used speed | Direction matters | avg velocity | Formula |"
        )

        result = ConceptGraphGrounder(Retriever(), max_depth=2).ground(
            analysis,
            subject="physics",
        )

        self.assertIn("Motion In A Straight Line", result.analysis)
        self.assertIn("Displacement; Vectors", result.analysis)
        self.assertEqual(result.validation["rows"][0]["concept_id"], "physics.motion.velocity")

    def test_grounding_does_not_rewrite_low_confidence_match(self):
        class Retriever:
            def validate(self, **kwargs):
                return ConceptGraphMatch(
                    matched=True,
                    confidence="low",
                    canonical_chapter="Electrostatics",
                    canonical_topic="Gauss Law",
                    canonical_microconcept="Electric Flux",
                    validation_notes=["weak match"],
                )

        analysis = (
            "| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | "
            "Exact Concept Gap | What You Must Deep-Dive |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| Q1 | Motion | Speed | Used speed | Direction matters | Average velocity | Vectors |"
        )

        result = ConceptGraphGrounder(Retriever()).ground(analysis)

        self.assertIn("| Q1 | Motion | Speed", result.analysis)
        self.assertNotIn("Electrostatics", result.analysis)
        self.assertEqual(result.validation["rows"][0]["confidence"], "low")

    def test_grounding_preserves_text_around_markdown_table(self):
        class Retriever:
            def validate(self, **kwargs):
                return ConceptGraphMatch(
                    matched=True,
                    confidence="medium",
                    canonical_chapter="Motion",
                    canonical_topic="Velocity",
                    canonical_microconcept="Average Velocity",
                )

        analysis = (
            "Intro note\n"
            "| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | "
            "Exact Concept Gap | What You Must Deep-Dive |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| Q1 | Motion | Speed | Used speed | Direction matters | avg velocity | Formula |\n"
            "Closing note"
        )

        result = ConceptGraphGrounder(Retriever()).ground(analysis)

        self.assertTrue(result.analysis.startswith("Intro note\n| Question Number"))
        self.assertTrue(result.analysis.endswith("Closing note"))
        self.assertIn("| Q1 | Motion | Velocity", result.analysis)

    def test_grounding_uses_deep_dive_and_reasoning_text_for_graph_query(self):
        class Retriever:
            def __init__(self):
                self.calls = []

            def validate(self, **kwargs):
                self.calls.append(kwargs)
                return ConceptGraphMatch(matched=False, confidence="none")

        retriever = Retriever()
        analysis = (
            "| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | "
            "Exact Concept Gap | What You Must Deep-Dive |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| Q1 | Motion | Velocity | Used speed | Direction matters | Formula application | "
            "Displacement vs distance and velocity-time graph slope |"
        )

        ConceptGraphGrounder(retriever).ground(analysis)

        concept_gap = retriever.calls[0]["concept_gap"]
        self.assertIn("Formula application", concept_gap)
        self.assertIn("Displacement vs distance", concept_gap)
        self.assertIn("Direction matters", concept_gap)

    def test_grounding_uses_fallback_validation_when_no_table_is_present(self):
        class Retriever:
            def validate(self, **kwargs):
                return ConceptGraphMatch(matched=False, confidence="none")

        result = ConceptGraphGrounder(Retriever()).ground("plain analysis")

        self.assertEqual(result.analysis, "plain analysis")
        self.assertEqual(result.validation["fallback"]["confidence"], "none")

    def test_grounding_ignores_tables_without_diagnosis_headers(self):
        class Retriever:
            def validate(self, **kwargs):
                return ConceptGraphMatch(matched=False, confidence="none")

        result = ConceptGraphGrounder(Retriever()).ground(
            "| A | B |\n| --- | --- |\n| one | two |"
        )

        self.assertEqual(result.validation["rows"], [])

    def test_grounding_degrades_to_baseline_on_graph_failure(self):
        class BrokenRetriever:
            def validate(self, **kwargs):
                raise RuntimeError("dynamo unavailable")

        analysis = (
            "| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | "
            "Exact Concept Gap | What You Must Deep-Dive |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| Q1 | Motion | Velocity | Used speed | Direction matters | Average velocity | Vectors |"
        )

        result = ConceptGraphGrounder(BrokenRetriever()).ground(analysis, subject="physics")

        self.assertEqual(result.analysis, analysis)
        self.assertTrue(result.validation["degraded_to_baseline"])


if __name__ == "__main__":
    unittest.main()
