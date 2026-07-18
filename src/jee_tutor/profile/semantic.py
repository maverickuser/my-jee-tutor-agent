from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jee_tutor.profile.evidence import ProfileEvidenceItem


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
    ):
        self.clusterer = clusterer

    def cluster(self, evidence_items: list[ProfileEvidenceItem]) -> list[SemanticGapCluster]:
        if self.clusterer is None:
            clusters = _deterministic_clusters(evidence_items)
        else:
            clusters = [
                SemanticGapCluster.model_validate(cluster)
                for cluster in self.clusterer(evidence_items)
            ]
        return validate_semantic_clusters(clusters, evidence_items)


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


def _deterministic_clusters(evidence_items: list[ProfileEvidenceItem]) -> list[SemanticGapCluster]:
    grouped: dict[str, list[ProfileEvidenceItem]] = defaultdict(list)
    for item in evidence_items:
        grouped[_normalize_gap(item.exact_concept_gap)].append(item)

    clusters: list[SemanticGapCluster] = []
    for index, (_key, items) in enumerate(sorted(grouped.items()), start=1):
        title = items[0].exact_concept_gap
        clusters.append(
            SemanticGapCluster(
                cluster_id=f"cluster-{index}",
                cluster_type="same_underlying_gap",
                title=title,
                evidence_ids=[item.evidence_id for item in items],
                rationale="Grouped by normalized exact concept gap.",
            )
        )
    return clusters


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
