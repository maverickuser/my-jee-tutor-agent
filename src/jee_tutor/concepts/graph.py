from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import re
import time
from typing import Any, Protocol

import boto3
from boto3.dynamodb.types import TypeDeserializer


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
logger = logging.getLogger(__name__)
QUALITY_RANK = {
    "expert_reviewed": 0,
    "reviewed": 1,
    "enriched": 2,
    "diagnostic": 3,
    "source_order": 4,
    "draft": 5,
}


@dataclass(frozen=True)
class ConceptGraphSettings:
    enabled: bool = False
    table_name: str | None = None
    region_name: str | None = None
    endpoint_url: str | None = None
    default_subject: str = "physics"
    max_depth: int = 2
    max_results: int = 5

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "ConceptGraphSettings":
        env = environ or os.environ
        return cls(
            enabled=_bool_env(env.get("CONCEPT_GRAPH_ENABLED"), False),
            table_name=env.get("CONCEPT_GRAPH_TABLE_NAME") or None,
            region_name=env.get("CONCEPT_GRAPH_REGION")
            or env.get("AWS_REGION")
            or env.get("AWS_DEFAULT_REGION"),
            endpoint_url=env.get("CONCEPT_GRAPH_ENDPOINT_URL") or None,
            default_subject=env.get("CONCEPT_GRAPH_DEFAULT_SUBJECT", "physics"),
            max_depth=_int_env(env.get("CONCEPT_GRAPH_MAX_DEPTH"), 2, minimum=1, maximum=5),
            max_results=_int_env(
                env.get("CONCEPT_GRAPH_MAX_RESULTS"),
                5,
                minimum=1,
                maximum=25,
            ),
        )


@dataclass
class ConceptGraphMatch:
    matched: bool
    concept_id: str | None = None
    canonical_chapter: str | None = None
    canonical_topic: str | None = None
    canonical_microconcept: str | None = None
    confidence: str = "none"
    validation_notes: list[str] = field(default_factory=list)
    prerequisites: list[dict[str, Any]] = field(default_factory=list)
    related_concepts: list[dict[str, Any]] = field(default_factory=list)
    common_confusions: list[str] = field(default_factory=list)
    deep_dive: list[str] = field(default_factory=list)
    error: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "concept_id": self.concept_id,
            "canonical_chapter": self.canonical_chapter,
            "canonical_topic": self.canonical_topic,
            "canonical_microconcept": self.canonical_microconcept,
            "confidence": self.confidence,
            "validation_notes": self.validation_notes,
            "prerequisites": self.prerequisites,
            "related_concepts": self.related_concepts,
            "common_confusions": self.common_confusions,
            "deep_dive": self.deep_dive,
            "error": self.error,
        }


class ConceptGraphRetriever(Protocol):
    def validate(
        self,
        *,
        subject: str | None = None,
        chapter: str | None = None,
        topic: str | None = None,
        microconcept: str | None = None,
        concept_gap: str | None = None,
        max_depth: int | None = None,
    ) -> ConceptGraphMatch:
        ...


class DisabledConceptGraphRetriever:
    def validate(self, **kwargs: Any) -> ConceptGraphMatch:
        return ConceptGraphMatch(
            matched=False,
            confidence="disabled",
            error="Concept graph retrieval is disabled or not configured.",
        )


class DynamoDBConceptGraphRetriever:
    def __init__(
        self,
        settings: ConceptGraphSettings | None = None,
        *,
        dynamodb_client: Any | None = None,
        sleep_fn: Any = time.sleep,
    ):
        self.settings = settings or ConceptGraphSettings.from_env()
        self._client = dynamodb_client
        self._deserializer = TypeDeserializer()
        self._sleep = sleep_fn

    def validate(
        self,
        *,
        subject: str | None = None,
        chapter: str | None = None,
        topic: str | None = None,
        microconcept: str | None = None,
        concept_gap: str | None = None,
        max_depth: int | None = None,
    ) -> ConceptGraphMatch:
        if not self.settings.enabled or not self.settings.table_name:
            return DisabledConceptGraphRetriever().validate()

        graph_version = self._active_version(subject)
        if not graph_version:
            return ConceptGraphMatch(
                matched=False,
                confidence="none",
                validation_notes=["Active concept graph version was not configured."],
            )
        concept_id = self._find_best_concept_id(
            graph_version=graph_version,
            subject=subject,
            chapter=chapter,
            topic=topic,
            microconcept=microconcept,
            concept_gap=concept_gap,
        )
        if not concept_id:
            return ConceptGraphMatch(
                matched=False,
                confidence="none",
                validation_notes=["No matching concept found in concept graph."],
            )

        concept = self._get_concept(graph_version, subject, concept_id)
        if not concept:
            return ConceptGraphMatch(
                matched=False,
                concept_id=concept_id,
                confidence="low",
                validation_notes=["Concept index matched but metadata was missing."],
            )

        depth = max_depth or self.settings.max_depth
        prerequisites = self._prerequisites(graph_version, subject, concept_id, depth)
        confidence, relevance_notes = _confidence_and_relevance_notes(
            concept,
            microconcept,
            concept_gap,
        )
        return ConceptGraphMatch(
            matched=True,
            concept_id=concept_id,
            canonical_chapter=concept.get("chapter"),
            canonical_topic=concept.get("topic"),
            canonical_microconcept=concept.get("micro_concept") or concept.get("name"),
            confidence=confidence,
            validation_notes=[
                *self._validation_notes(chapter, topic, microconcept, concept),
                *relevance_notes,
            ],
            prerequisites=prerequisites,
            common_confusions=list(concept.get("common_confusions") or []),
            deep_dive=self._deep_dive(concept, prerequisites),
        )

    def _active_version(self, subject: str | None) -> str | None:
        subject_key = self._subject(subject)
        response = self._client_or_create().get_item(
            TableName=self.settings.table_name,
            Key={
                "PK": {"S": f"GRAPH#{subject_key}"},
                "SK": {"S": "ACTIVE"},
            },
        )
        item = self._deserialize_item(response.get("Item"))
        version = item.get("graph_version") or item.get("version")
        return str(version) if version else None

    def _find_best_concept_id(
        self,
        *,
        graph_version: str,
        subject: str | None,
        chapter: str | None,
        topic: str | None,
        microconcept: str | None,
        concept_gap: str | None,
    ) -> str | None:
        candidates = self._candidate_concept_ids(
            graph_version=graph_version,
            subject=subject,
            chapter=chapter,
            topic=topic,
            microconcept=microconcept,
            concept_gap=concept_gap,
        )
        if not candidates:
            return None

        scored = []
        for index, concept_id in enumerate(candidates):
            concept = self._get_concept(graph_version, subject, concept_id)
            scored.append(
                (
                    _concept_relevance_score(concept, microconcept, concept_gap, topic),
                    _concept_relevance_score(concept, microconcept, concept_gap),
                    concept is not None,
                    index,
                    concept_id,
                )
        )
        scored.sort(key=lambda value: (-value[0], -value[1], not value[2], value[3]))
        _, _, _, _, best_concept_id = scored[0]
        return best_concept_id

    def _candidate_concept_ids(
        self,
        *,
        graph_version: str,
        subject: str | None,
        chapter: str | None,
        topic: str | None,
        microconcept: str | None,
        concept_gap: str | None,
    ) -> list[str]:
        subject_key = self._subject(subject)
        candidate_ids: list[str] = []
        if chapter and topic:
            chapter_pk = (
                f"GRAPH#{subject_key}#VERSION#{graph_version}#CHAPTER#{normalize_key(chapter)}"
            )
            topic_prefix = f"TOPIC#{normalize_key(topic)}#CONCEPT#"
            response = self._client_or_create().query(
                TableName=self.settings.table_name,
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
                ExpressionAttributeValues={
                    ":pk": {"S": chapter_pk},
                    ":sk": {"S": topic_prefix},
                },
                Limit=self.settings.max_results,
            )
            for item in response.get("Items", []):
                if concept_id := self._concept_id_from_index_item(item):
                    candidate_ids.append(concept_id)

        for token in self._search_tokens(microconcept, concept_gap, topic):
            response = self._client_or_create().query(
                TableName=self.settings.table_name,
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
                ExpressionAttributeValues={
                    ":pk": {
                        "S": f"GRAPH#{subject_key}#VERSION#{graph_version}#TERM#{token}"
                    },
                    ":sk": {"S": "CONCEPT#"},
                },
                Limit=self.settings.max_results,
            )
            for item in response.get("Items", []):
                if concept_id := self._concept_id_from_index_item(item):
                    candidate_ids.append(concept_id)
        return _dedupe(candidate_ids)

    def _get_concept(
        self,
        graph_version: str,
        subject: str | None,
        concept_id: str,
    ) -> dict[str, Any] | None:
        response = self._client_or_create().get_item(
            TableName=self.settings.table_name,
            Key={
                "PK": {
                    "S": (
                        f"GRAPH#{self._subject(subject)}#VERSION#{graph_version}"
                        f"#CONCEPT#{concept_id}"
                    )
                },
                "SK": {"S": "META"},
            },
        )
        return self._deserialize_item(response.get("Item")) or None

    def _prerequisites(
        self,
        graph_version: str,
        subject: str | None,
        concept_id: str,
        max_depth: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for depth in range(1, max_depth + 1):
            response = self._client_or_create().query(
                TableName=self.settings.table_name,
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
                ExpressionAttributeValues={
                    ":pk": {
                        "S": (
                            f"GRAPH#{self._subject(subject)}#VERSION#{graph_version}"
                            f"#CONCEPT#{concept_id}"
                        )
                    },
                    ":sk": {"S": f"PREREQ#D{depth}#"},
                },
                Limit=self.settings.max_results,
            )
            items.extend(self._deserialize_item(item) for item in response.get("Items", []))

        items = sorted(items, key=_quality_sort_key)[: self.settings.max_results]
        self._enrich_prerequisite_edges(graph_version, subject, items)
        return items

    def _enrich_prerequisite_edges(
        self,
        graph_version: str,
        subject: str | None,
        prerequisites: list[dict[str, Any]],
    ) -> None:
        prerequisite_ids = []
        for edge in prerequisites:
            prerequisite_id = edge.get("prerequisite_id") or _prerequisite_id_from_sk(
                str(edge.get("SK", ""))
            )
            if not prerequisite_id:
                continue
            edge["prerequisite_id"] = prerequisite_id
            prerequisite_ids.append(str(prerequisite_id))

        if not prerequisite_ids:
            return

        keys = [
            {
                "PK": {
                    "S": (
                        f"GRAPH#{self._subject(subject)}#VERSION#{graph_version}"
                        f"#CONCEPT#{prerequisite_id}"
                    )
                },
                "SK": {"S": "META"},
            }
            for prerequisite_id in _dedupe(prerequisite_ids)
        ]
        responses = self._batch_get_all(keys)
        metadata_by_id = {
            _concept_id_from_pk(str(item.get("PK", ""))): item
            for item in responses
        }
        for edge in prerequisites:
            metadata = metadata_by_id.get(str(edge.get("prerequisite_id")))
            if not metadata:
                continue
            edge["name"] = metadata.get("micro_concept") or metadata.get("name")
            edge["chapter"] = metadata.get("chapter")
            edge["topic"] = metadata.get("topic")

    def _batch_get_all(self, keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not keys:
            return []

        request_items = {self.settings.table_name: {"Keys": keys}}
        responses: list[dict[str, Any]] = []
        for _attempt in range(3):
            response = self._client_or_create().batch_get_item(RequestItems=request_items)
            responses.extend(
                self._deserialize_item(raw_item)
                for raw_item in response.get("Responses", {}).get(self.settings.table_name, [])
            )
            request_items = response.get("UnprocessedKeys") or {}
            if not request_items:
                break
            self._sleep(0.05 * (2**_attempt))
        if request_items:
            logger.warning(
                "concept_graph_batch_get_unprocessed_keys table=%s key_count=%s",
                self.settings.table_name,
                len(request_items.get(self.settings.table_name, {}).get("Keys", [])),
            )
        return responses

    def _deep_dive(self, concept: dict[str, Any], prerequisites: list[dict[str, Any]]) -> list[str]:
        values = []
        if skill := concept.get("testable_skill"):
            values.append(str(skill))
        for prereq in prerequisites:
            name = prereq.get("name") or prereq.get("concept") or prereq.get("prerequisite_id")
            if name:
                values.append(str(name))
        return values[: self.settings.max_results]

    @staticmethod
    def _validation_notes(
        chapter: str | None,
        topic: str | None,
        microconcept: str | None,
        concept: dict[str, Any],
    ) -> list[str]:
        notes = []
        for requested, canonical, label in (
            (chapter, concept.get("chapter"), "chapter"),
            (topic, concept.get("topic"), "topic"),
            (microconcept, concept.get("micro_concept") or concept.get("name"), "microconcept"),
        ):
            if requested and canonical and normalize_key(requested) != normalize_key(str(canonical)):
                notes.append(f"{label} normalized from {requested} to {canonical}.")
        return notes

    def _search_tokens(self, *values: str | None) -> list[str]:
        tokens = []
        for value in values:
            if not value:
                continue
            tokens.extend(TOKEN_PATTERN.findall(value.lower()))
        unique = []
        for token in tokens:
            if len(token) > 2 and token not in unique:
                unique.append(token)
        return unique[: self.settings.max_results]

    def _concept_id_from_index_item(self, item: dict[str, Any]) -> str | None:
        value = self._deserialize_item(item)
        if concept_id := value.get("concept_id"):
            return str(concept_id)
        sk = str(value.get("SK", ""))
        if "#CONCEPT#" in sk:
            return sk.rsplit("#CONCEPT#", 1)[1]
        if sk.startswith("CONCEPT#"):
            return sk.removeprefix("CONCEPT#")
        return None

    def _client_or_create(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "dynamodb",
                region_name=self.settings.region_name,
                endpoint_url=self.settings.endpoint_url,
            )
        return self._client

    def _deserialize_item(self, item: dict[str, Any] | None) -> dict[str, Any]:
        if not item:
            return {}
        if all(isinstance(value, dict) and len(value) == 1 for value in item.values()):
            return {key: self._deserializer.deserialize(value) for key, value in item.items()}
        return dict(item)

    def _subject(self, subject: str | None) -> str:
        return normalize_key(subject or self.settings.default_subject)


def normalize_key(value: str) -> str:
    return "_".join(TOKEN_PATTERN.findall(value.lower()))


def _quality_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    quality = str(item.get("quality") or item.get("status") or "draft")
    return (QUALITY_RANK.get(quality, 99), str(item.get("SK", "")))


def _concept_relevance_score(
    concept: dict[str, Any] | None,
    *query_values: str | None,
) -> int:
    if not concept:
        return 0
    query_tokens = set(_tokens(*query_values))
    if not query_tokens:
        return 0
    aliases = concept.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = [aliases]
    fields = [
        concept.get("name"),
        concept.get("micro_concept"),
        concept.get("topic"),
        concept.get("chapter"),
        concept.get("concept_id"),
        *aliases,
    ]
    concept_tokens = set(_tokens(*(str(field) for field in fields if field)))
    return len(query_tokens & concept_tokens)


def _tokens(*values: str | None) -> list[str]:
    tokens: list[str] = []
    for value in values:
        if not value:
            continue
        tokens.extend(token for token in TOKEN_PATTERN.findall(value.lower()) if len(token) > 2)
    return tokens


def _dedupe(values: list[str]) -> list[str]:
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


def _prerequisite_id_from_sk(sk: str) -> str | None:
    parts = sk.split("#", 3)
    if len(parts) == 4 and parts[0] == "PREREQ":
        return parts[3]
    return None


def _concept_id_from_pk(pk: str) -> str:
    return pk.rsplit("#CONCEPT#", 1)[-1]


def _bool_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _confidence_and_relevance_notes(
    concept: dict[str, Any],
    microconcept: str | None,
    concept_gap: str | None,
) -> tuple[str, list[str]]:
    if not _tokens(microconcept, concept_gap):
        return "medium", []
    if _concept_relevance_score(concept, microconcept, concept_gap) > 0:
        return "high", []
    return (
        "low",
        [
            "Concept selected from graph index, but specific diagnosis terms did not "
            "overlap concept metadata."
        ],
    )


def _int_env(
    value: str | None,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("invalid_concept_graph_int_env value=%s default=%s", value, default)
        return default
    if parsed < minimum:
        logger.warning(
            "concept_graph_int_env_below_minimum value=%s minimum=%s default=%s",
            parsed,
            minimum,
            default,
        )
        return default
    if parsed > maximum:
        logger.warning(
            "concept_graph_int_env_above_maximum value=%s maximum=%s default=%s",
            parsed,
            maximum,
            default,
        )
        return default
    return parsed
