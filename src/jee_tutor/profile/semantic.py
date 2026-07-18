from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from copy import deepcopy
import json
import os
import re
from typing import Any, Literal, Protocol

from litellm import completion
from pydantic import BaseModel, ConfigDict, Field, field_validator

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.profile.embeddings import EvidenceEmbeddingRecord, EvidenceEmbeddingService
from jee_tutor.profile.evidence import ProfileEvidenceItem

DEFAULT_SEMANTIC_CLUSTER_MODEL = "gemini/gemini-2.5-pro"
SEMANTIC_CLUSTER_SCHEMA_NAME = "student_profile_semantic_clusters"
SEMANTIC_CLUSTER_SCHEMA_VERSION = "1.0"


ClusterType = Literal[
    "same_underlying_gap",
    "same_wrong_approach",
    "same_prerequisite_weakness",
    "same_execution_pattern",
    "related_distinct_subgaps",
    "unrelated",
]
RecurrenceLabel = Literal["recurring", "isolated_or_early_indicator"]


class SemanticGapCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str = Field(min_length=1)
    cluster_type: ClusterType
    title: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def reject_duplicate_evidence_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Semantic cluster contains duplicate evidence ids.")
        return value


class SemanticCandidateCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    max_similarity: float | None = None

    @field_validator("evidence_ids")
    @classmethod
    def reject_duplicate_candidate_evidence_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Semantic candidate contains duplicate evidence ids.")
        return value


class SemanticClusterClassifierOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clusters: list[SemanticGapCluster] = Field(min_length=1)


class ClassifiedGapCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster: SemanticGapCluster
    recurrence_label: RecurrenceLabel
    diagnosis_report_count: int = Field(ge=1)
    question_count: int = Field(ge=1)


class ChapterTopicProfileMapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    recurring_cluster_ids: list[str] = Field(default_factory=list)
    isolated_cluster_ids: list[str] = Field(default_factory=list)


class LongitudinalEvidencePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    diagnosis_report_count: int = Field(ge=0)
    question_count: int = Field(ge=0)
    evidence_index: dict[str, ProfileEvidenceItem] = Field(default_factory=dict)
    clusters: list[ClassifiedGapCluster] = Field(default_factory=list)
    chapter_topic_map: list[ChapterTopicProfileMapEntry] = Field(default_factory=list)
    mistake_pattern_summary: list[str] = Field(default_factory=list)


class SemanticGapAnalyzer:
    def __init__(
        self,
        *,
        clusterer: Callable[[list[ProfileEvidenceItem]], Any] | None = None,
        embedding_service: EvidenceEmbeddingService | None = None,
        classifier: "SemanticClusterClassifier | None" = None,
        similarity_threshold: float = 0.78,
    ):
        self.clusterer = clusterer
        self.embedding_service = embedding_service
        self.classifier = classifier
        self.similarity_threshold = similarity_threshold

    def cluster(
        self,
        evidence_items: list[ProfileEvidenceItem],
        *,
        subject: str | None = None,
    ) -> list[SemanticGapCluster]:
        if self.clusterer is None:
            resolved_subject = subject or _single_subject(evidence_items)
            embedding_service = self.embedding_service or EvidenceEmbeddingService()
            classifier = self.classifier or LiteLLMSemanticClusterClassifier()
            embedding_records = embedding_service.ensure_embeddings(
                subject=resolved_subject,
                evidence_items=evidence_items,
            )
            candidates = build_embedding_candidate_clusters(
                evidence_items=evidence_items,
                embedding_records=embedding_records,
                similarity_threshold=self.similarity_threshold,
            )
            clusters = classifier.classify(
                evidence_items=evidence_items,
                candidates=candidates,
            )
        else:
            clusters = [
                SemanticGapCluster.model_validate(cluster)
                for cluster in self.clusterer(evidence_items)
            ]
        return validate_semantic_clusters(clusters, evidence_items)


class SemanticClusterClassifier(Protocol):
    def classify(
        self,
        *,
        evidence_items: list[ProfileEvidenceItem],
        candidates: list[SemanticCandidateCluster],
    ) -> list[SemanticGapCluster]: ...


class LiteLLMSemanticClusterClassifier:
    def __init__(
        self,
        *,
        model_config: "SemanticClusterModelConfig | None" = None,
        completion_fn: Callable[..., Any] | None = None,
    ):
        self.model_config = model_config or SemanticClusterModelConfig()
        self.completion_fn = completion_fn or completion

    def classify(
        self,
        *,
        evidence_items: list[ProfileEvidenceItem],
        candidates: list[SemanticCandidateCluster],
    ) -> list[SemanticGapCluster]:
        settings = self.model_config.resolve()
        completion_kwargs = settings.to_litellm_kwargs()
        completion_kwargs.setdefault("num_retries", 0)
        response = self.completion_fn(
            **completion_kwargs,
            messages=[
                {
                    "role": "system",
                    "content": _semantic_cluster_system_prompt(),
                },
                {
                    "role": "user",
                    "content": _semantic_cluster_user_prompt(
                        evidence_items=evidence_items,
                        candidates=candidates,
                    ),
                },
            ],
            response_format=semantic_cluster_response_format(),
            caching=False,
            cache={"no-cache": True},
        )
        content = response["choices"][0]["message"]["content"].strip()
        return SemanticClusterClassifierOutput.model_validate_json(content).clusters


class SemanticClusterModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    api_key: str | None = None
    api_base: str | None = None
    completion_options: dict[str, Any] | None = None

    def to_litellm_kwargs(self) -> dict[str, Any]:
        kwargs = deepcopy(self.completion_options) if self.completion_options else {}
        kwargs["model"] = self.model
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        return kwargs


class SemanticClusterModelConfig:
    def __init__(
        self,
        *,
        environ: dict[str, str] | None = None,
        config: Any | None = None,
    ):
        self.environ = environ or os.environ
        self.config = config or LLMConfig.load()

    def resolve(self) -> SemanticClusterModelSettings:
        model = (
            self.environ.get("PROFILE_SEMANTIC_CLUSTER_MODEL")
            or _config_get(self.config, "semantic_clustering", "model")
            or self.environ.get("PROFILE_REPORT_MODEL")
            or DEFAULT_SEMANTIC_CLUSTER_MODEL
        )
        completion_options = _config_section(self.config, "completion")
        completion_options.setdefault("timeout", 180)
        return SemanticClusterModelSettings(
            model=model,
            api_key=_api_key_for_model(model, self.environ),
            api_base=self.environ.get("LITELLM_BASE_URL")
            or _config_get(self.config, "litellm", "api_base"),
            completion_options=completion_options,
        )


def validate_semantic_clusters(
    clusters: list[SemanticGapCluster],
    evidence_items: list[ProfileEvidenceItem],
) -> list[SemanticGapCluster]:
    known_ids = {item.evidence_id for item in evidence_items}
    assigned_non_related: dict[str, str] = {}
    for cluster in clusters:
        unknown_ids = set(cluster.evidence_ids) - known_ids
        if unknown_ids:
            raise ValueError(f"Semantic cluster references unknown evidence ids: {sorted(unknown_ids)}")
        if cluster.cluster_type != "related_distinct_subgaps":
            for evidence_id in cluster.evidence_ids:
                if evidence_id in assigned_non_related:
                    raise ValueError(
                        "Semantic cluster assigns evidence to incompatible duplicate clusters."
                    )
                assigned_non_related[evidence_id] = cluster.cluster_id
    return clusters


def build_embedding_candidate_clusters(
    *,
    evidence_items: list[ProfileEvidenceItem],
    embedding_records: dict[str, EvidenceEmbeddingRecord],
    similarity_threshold: float = 0.78,
) -> list[SemanticCandidateCluster]:
    missing_ids = [
        item.evidence_id
        for item in evidence_items
        if item.evidence_id not in embedding_records
    ]
    if missing_ids:
        raise ValueError(f"Missing embeddings for evidence ids: {missing_ids}")

    evidence_ids = [item.evidence_id for item in evidence_items]
    graph: dict[str, set[str]] = {evidence_id: {evidence_id} for evidence_id in evidence_ids}
    max_similarity: dict[frozenset[str], float] = {}
    for left_index, left_id in enumerate(evidence_ids):
        for right_id in evidence_ids[left_index + 1 :]:
            score = cosine_similarity(
                embedding_records[left_id].embedding,
                embedding_records[right_id].embedding,
            )
            if score >= similarity_threshold:
                graph[left_id].add(right_id)
                graph[right_id].add(left_id)
                max_similarity[frozenset({left_id, right_id})] = score

    for group in _normalized_gap_candidate_groups(evidence_items):
        for left_id in group:
            graph[left_id].update(group)

    candidates: list[SemanticCandidateCluster] = []
    seen: set[str] = set()
    for evidence_id in evidence_ids:
        if evidence_id in seen:
            continue
        component = _connected_component(evidence_id, graph)
        seen.update(component)
        ordered_ids = [item.evidence_id for item in evidence_items if item.evidence_id in component]
        component_scores = [
            score
            for pair, score in max_similarity.items()
            if pair.issubset(component)
        ]
        candidates.append(
            SemanticCandidateCluster(
                candidate_id=f"candidate-{len(candidates) + 1}",
                evidence_ids=ordered_ids,
                rationale="Embedding cosine similarity and normalized text matches.",
                max_similarity=max(component_scores) if component_scores else None,
            )
        )
    return candidates


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding vectors must have the same dimensions.")
    left_norm = sum(component * component for component in left) ** 0.5
    right_norm = sum(component * component for component in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = sum(left_component * right_component for left_component, right_component in zip(left, right, strict=True))
    return dot_product / (left_norm * right_norm)


def build_longitudinal_evidence_pack(
    *,
    subject: str,
    evidence_items: list[ProfileEvidenceItem],
    clusters: list[SemanticGapCluster],
) -> LongitudinalEvidencePack:
    evidence_index = {item.evidence_id: item for item in evidence_items}
    classified = [
        _classify_cluster(cluster, evidence_index)
        for cluster in validate_semantic_clusters(clusters, evidence_items)
    ]
    return LongitudinalEvidencePack(
        subject=subject,
        diagnosis_report_count=len({item.diagnosis_report_id for item in evidence_items}),
        question_count=len(evidence_items),
        evidence_index=evidence_index,
        clusters=classified,
        chapter_topic_map=_chapter_topic_map(classified, evidence_index),
        mistake_pattern_summary=_mistake_pattern_summary(classified),
    )


def _classify_cluster(
    cluster: SemanticGapCluster,
    evidence_index: dict[str, ProfileEvidenceItem],
) -> ClassifiedGapCluster:
    report_ids = {
        evidence_index[evidence_id].diagnosis_report_id
        for evidence_id in cluster.evidence_ids
    }
    report_count = len(report_ids)
    return ClassifiedGapCluster(
        cluster=cluster,
        recurrence_label="recurring"
        if report_count >= 2
        else "isolated_or_early_indicator",
        diagnosis_report_count=report_count,
        question_count=len(cluster.evidence_ids),
    )


def _chapter_topic_map(
    clusters: list[ClassifiedGapCluster],
    evidence_index: dict[str, ProfileEvidenceItem],
) -> list[ChapterTopicProfileMapEntry]:
    grouped: dict[tuple[str, str], ChapterTopicProfileMapEntry] = {}
    for classified in clusters:
        for evidence_id in classified.cluster.evidence_ids:
            evidence = evidence_index[evidence_id]
            key = (evidence.chapter, evidence.topic)
            entry = grouped.setdefault(
                key,
                ChapterTopicProfileMapEntry(chapter=evidence.chapter, topic=evidence.topic),
            )
            if classified.recurrence_label == "recurring":
                if classified.cluster.cluster_id not in entry.recurring_cluster_ids:
                    entry.recurring_cluster_ids.append(classified.cluster.cluster_id)
            elif classified.cluster.cluster_id not in entry.isolated_cluster_ids:
                entry.isolated_cluster_ids.append(classified.cluster.cluster_id)
    return list(grouped.values())


def _mistake_pattern_summary(clusters: list[ClassifiedGapCluster]) -> list[str]:
    recurring = [cluster for cluster in clusters if cluster.recurrence_label == "recurring"]
    isolated = [cluster for cluster in clusters if cluster.recurrence_label != "recurring"]
    summary: list[str] = []
    if recurring:
        summary.append(f"{len(recurring)} recurring learning gap cluster(s) found.")
    if isolated:
        summary.append(f"{len(isolated)} isolated or early-indicator cluster(s) found.")
    return summary


def _normalize_gap(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return re.sub(r"\s+", " ", normalized).strip()


def _single_subject(evidence_items: list[ProfileEvidenceItem]) -> str:
    subjects = {item.subject for item in evidence_items}
    if len(subjects) != 1:
        raise ValueError("Semantic analysis requires evidence from exactly one subject.")
    return next(iter(subjects))


def _normalized_gap_candidate_groups(
    evidence_items: list[ProfileEvidenceItem],
) -> list[set[str]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for item in evidence_items:
        grouped[_normalize_gap(item.exact_concept_gap)].add(item.evidence_id)
    return [group for group in grouped.values() if len(group) > 1]


def _connected_component(start: str, graph: dict[str, set[str]]) -> set[str]:
    component: set[str] = set()
    stack = [start]
    while stack:
        evidence_id = stack.pop()
        if evidence_id in component:
            continue
        component.add(evidence_id)
        stack.extend(sorted(graph[evidence_id] - component))
    return component


def semantic_cluster_response_format() -> dict[str, object]:
    schema = SemanticClusterClassifierOutput.model_json_schema()
    schema["additionalProperties"] = False
    return {
        "type": "json_schema",
        "json_schema": {
            "name": SEMANTIC_CLUSTER_SCHEMA_NAME,
            "schema": schema,
            "strict": True,
        },
    }


def _semantic_cluster_system_prompt() -> str:
    return (
        "You classify compact JEE diagnosis evidence into semantic learning-gap clusters. "
        "Use only the provided evidence ids and candidate groups. Return JSON only. "
        "Every evidence item must appear in at least one final cluster. Do not invent ids. "
        "Use cluster_type values exactly from the schema."
    )


def _semantic_cluster_user_prompt(
    *,
    evidence_items: list[ProfileEvidenceItem],
    candidates: list[SemanticCandidateCluster],
) -> str:
    payload = {
        "instructions": [
            "Classify each candidate group into typed semantic clusters.",
            "Split a candidate if it contains unrelated evidence.",
            "Use unrelated for isolated evidence when no supported relation exists.",
            "Preserve evidence ids exactly.",
        ],
        "evidence_items": [
            {
                "evidence_id": item.evidence_id,
                "diagnosis_report_id": item.diagnosis_report_id,
                "question_number": item.question_number,
                "subject": item.subject,
                "chapter": item.chapter,
                "topic": item.topic,
                "exact_concept_gap": item.exact_concept_gap,
                "likely_thought": item.likely_thought,
                "why_wrong": item.why_wrong,
                "deep_dive_recommendation": item.deep_dive_recommendation,
            }
            for item in evidence_items
        ],
        "candidate_clusters": [candidate.model_dump() for candidate in candidates],
    }
    return json.dumps(payload, sort_keys=True)


def _api_key_for_model(model: str, environ: dict[str, str]) -> str | None:
    normalized = model.casefold()
    if normalized.startswith("openai/"):
        return environ.get("OPENAI_API_KEY") or environ.get("LITELLM_API_KEY")
    if normalized.startswith("gemini/"):
        return environ.get("GOOGLE_API_KEY") or environ.get("LITELLM_API_KEY")
    return environ.get("LITELLM_API_KEY") or None


def _config_section(config: Any, section: str) -> dict[str, Any]:
    if hasattr(config, "section"):
        return config.section(section)
    value = config.get(section, {})
    return dict(value) if isinstance(value, dict) else {}


def _config_get(
    config: Any,
    section: str,
    key: str,
    default: Any = None,
) -> Any:
    if hasattr(config, "section"):
        return config.get(section, key, default)
    value = config.get(section, {})
    if not isinstance(value, dict):
        return default
    return value.get(key, default)
