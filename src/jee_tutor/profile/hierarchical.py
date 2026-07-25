from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
from typing import Literal, Protocol

from litellm import completion
from pydantic import BaseModel, ConfigDict, Field, field_validator

from jee_tutor.profile.embeddings import EvidenceEmbeddingService
from jee_tutor.profile.evidence import ProfileEvidenceItem
from jee_tutor.profile.semantic import (
    SemanticCandidateCluster,
    SemanticClusterModelConfig,
    build_embedding_candidate_clusters,
)


Confidence = Literal["high", "medium", "low"]


class LocalConceptGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str = Field(min_length=1)
    canonical_chapter: str = Field(min_length=1)
    canonical_topic: str = Field(min_length=1)
    required_concept: str = Field(min_length=1)
    concept_gap: str = Field(min_length=1)
    shared_misconception: str = Field(min_length=1)
    corrective_concept: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Confidence
    rationale: str = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Local concept gap contains duplicate evidence ids.")
        return value


class LocalConceptGapOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gaps: list[LocalConceptGap] = Field(default_factory=list)


class ValidatedRecurringGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap: LocalConceptGap
    diagnosis_report_count: int = Field(ge=2)
    question_count: int = Field(ge=2)


class BroaderPatternManifestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str = Field(min_length=1)
    chapter: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    manifestation: str = Field(min_length=1)


class BroaderConceptualPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    shared_reasoning_gap: str = Field(min_length=1)
    common_corrective_principle: str = Field(min_length=1)
    component_gap_ids: list[str] = Field(min_length=2)
    manifestations: list[BroaderPatternManifestation] = Field(min_length=2)
    confidence: Confidence
    rationale: str = Field(min_length=1)

    @field_validator("component_gap_ids")
    @classmethod
    def unique_components(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Broader pattern contains duplicate component gaps.")
        return value


class BroaderPatternOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patterns: list[BroaderConceptualPattern] = Field(default_factory=list)


class LongitudinalEvidencePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    diagnosis_report_count: int = Field(ge=0)
    question_count: int = Field(ge=0)
    evidence_index: dict[str, ProfileEvidenceItem] = Field(default_factory=dict)
    recurring_gaps: list[ValidatedRecurringGap] = Field(default_factory=list)
    broader_patterns: list[BroaderConceptualPattern] = Field(default_factory=list)


class LocalGapClassifier(Protocol):
    def classify(
        self,
        *,
        evidence_items: list[ProfileEvidenceItem],
        candidates: list[SemanticCandidateCluster],
    ) -> list[LocalConceptGap]: ...


class BroaderPatternClassifier(Protocol):
    def classify(
        self,
        *,
        recurring_gaps: list[ValidatedRecurringGap],
        candidates: list[SemanticCandidateCluster],
    ) -> list[BroaderConceptualPattern]: ...


class LocalConceptGapAnalyzer:
    def __init__(
        self,
        *,
        embedding_service: EvidenceEmbeddingService | None = None,
        classifier: LocalGapClassifier | None = None,
        analyzer: Callable[[list[ProfileEvidenceItem]], list[LocalConceptGap]] | None = None,
        similarity_threshold: float = 0.78,
    ):
        self.embedding_service = embedding_service
        self.classifier = classifier
        self.analyzer = analyzer
        self.similarity_threshold = similarity_threshold

    def analyze(
        self,
        evidence_items: list[ProfileEvidenceItem],
        *,
        subject: str,
    ) -> list[LocalConceptGap]:
        if self.analyzer is not None:
            return validate_local_gaps(self.analyzer(evidence_items), evidence_items)
        embedding_service = self.embedding_service or EvidenceEmbeddingService()
        records = embedding_service.ensure_embeddings(
            subject=subject,
            evidence_items=evidence_items,
        )
        candidates = build_local_candidate_clusters(
            evidence_items=evidence_items,
            embedding_records=records,
            similarity_threshold=self.similarity_threshold,
        )
        classifier = self.classifier or LiteLLMLocalGapClassifier()
        return validate_local_gaps(
            classifier.classify(evidence_items=evidence_items, candidates=candidates),
            evidence_items,
        )


class BroaderPatternAnalyzer:
    def __init__(
        self,
        *,
        embedding_service: EvidenceEmbeddingService | None = None,
        classifier: BroaderPatternClassifier | None = None,
        analyzer: Callable[
            [list[ValidatedRecurringGap]], list[BroaderConceptualPattern]
        ]
        | None = None,
        similarity_threshold: float = 0.72,
    ):
        self.embedding_service = embedding_service
        self.classifier = classifier
        self.analyzer = analyzer
        self.similarity_threshold = similarity_threshold

    def analyze(
        self,
        recurring_gaps: list[ValidatedRecurringGap],
        *,
        evidence_index: dict[str, ProfileEvidenceItem],
        subject: str,
    ) -> list[BroaderConceptualPattern]:
        if len({_location(item.gap) for item in recurring_gaps}) < 2:
            return []
        if self.analyzer is not None:
            return validate_broader_patterns(self.analyzer(recurring_gaps), recurring_gaps)
        synthetic = [
            _gap_as_evidence(item.gap, evidence_index)
            for item in recurring_gaps
        ]
        embedding_service = self.embedding_service or EvidenceEmbeddingService(
            input_version="local-gap-v1"
        )
        records = embedding_service.ensure_embeddings(
            subject=subject,
            evidence_items=synthetic,
        )
        candidates = [
            candidate
            for candidate in build_embedding_candidate_clusters(
                evidence_items=synthetic,
                embedding_records=records,
                similarity_threshold=self.similarity_threshold,
            )
            if len(candidate.evidence_ids) >= 2
            and len(
                {
                    _location(_gap_by_id(recurring_gaps, gap_id).gap)
                    for gap_id in candidate.evidence_ids
                }
            )
            >= 2
        ]
        if not candidates:
            return []
        classifier = self.classifier or LiteLLMBroaderPatternClassifier()
        return validate_broader_patterns(
            classifier.classify(recurring_gaps=recurring_gaps, candidates=candidates),
            recurring_gaps,
        )


def build_local_candidate_clusters(
    *,
    evidence_items: list[ProfileEvidenceItem],
    embedding_records,
    similarity_threshold: float,
) -> list[SemanticCandidateCluster]:
    grouped: dict[tuple[str, str], list[ProfileEvidenceItem]] = {}
    for item in evidence_items:
        grouped.setdefault(
            (item.canonical_chapter.casefold(), item.canonical_topic.casefold()),
            [],
        ).append(item)
    candidates: list[SemanticCandidateCluster] = []
    for context_index, items in enumerate(grouped.values(), start=1):
        local = build_embedding_candidate_clusters(
            evidence_items=items,
            embedding_records={
                item.evidence_id: embedding_records[item.evidence_id] for item in items
            },
            similarity_threshold=similarity_threshold,
        )
        for candidate_index, candidate in enumerate(local, start=1):
            candidate.candidate_id = f"context-{context_index}-candidate-{candidate_index}"
            candidates.append(candidate)
    return candidates


def validate_local_gaps(
    gaps: list[LocalConceptGap],
    evidence_items: list[ProfileEvidenceItem],
) -> list[LocalConceptGap]:
    index = {item.evidence_id: item for item in evidence_items}
    assigned: set[str] = set()
    for gap in gaps:
        unknown = set(gap.evidence_ids) - set(index)
        if unknown:
            raise ValueError(f"Local concept gap references unknown evidence ids: {sorted(unknown)}")
        contexts = {
            (
                index[evidence_id].canonical_chapter.casefold(),
                index[evidence_id].canonical_topic.casefold(),
            )
            for evidence_id in gap.evidence_ids
        }
        if len(contexts) != 1:
            raise ValueError("Local concept gap spans multiple chapter/topic contexts.")
        if assigned.intersection(gap.evidence_ids):
            raise ValueError("Evidence is assigned to multiple local concept gaps.")
        assigned.update(gap.evidence_ids)
    return gaps


def recurring_local_gaps(
    gaps: list[LocalConceptGap],
    evidence_index: dict[str, ProfileEvidenceItem],
) -> list[ValidatedRecurringGap]:
    recurring: list[ValidatedRecurringGap] = []
    for gap in gaps:
        report_ids = {
            evidence_index[evidence_id].diagnosis_report_id
            for evidence_id in gap.evidence_ids
        }
        if len(report_ids) < 2 or gap.confidence == "low":
            continue
        recurring.append(
            ValidatedRecurringGap(
                gap=gap,
                diagnosis_report_count=len(report_ids),
                question_count=len(gap.evidence_ids),
            )
        )
    return recurring


def validate_broader_patterns(
    patterns: list[BroaderConceptualPattern],
    recurring_gaps: list[ValidatedRecurringGap],
) -> list[BroaderConceptualPattern]:
    gap_index = {item.gap.gap_id: item for item in recurring_gaps}
    for pattern in patterns:
        unknown = set(pattern.component_gap_ids) - set(gap_index)
        if unknown:
            raise ValueError(f"Broader pattern references unknown gap ids: {sorted(unknown)}")
        contexts = {
            _location(gap_index[gap_id].gap)
            for gap_id in pattern.component_gap_ids
        }
        if len(contexts) < 2:
            raise ValueError("Broader pattern must span distinct chapter/topic contexts.")
        if pattern.confidence == "low":
            raise ValueError("Low-confidence broader patterns are not reportable.")
        if {item.gap_id for item in pattern.manifestations} != set(
            pattern.component_gap_ids
        ):
            raise ValueError("Broader pattern manifestations must cover component gaps.")
    return patterns


def build_longitudinal_evidence_pack(
    *,
    subject: str,
    evidence_items: list[ProfileEvidenceItem],
    local_gaps: list[LocalConceptGap],
    broader_patterns: list[BroaderConceptualPattern],
) -> LongitudinalEvidencePack:
    evidence_index = {item.evidence_id: item for item in evidence_items}
    recurring = recurring_local_gaps(local_gaps, evidence_index)
    validated_patterns = validate_broader_patterns(broader_patterns, recurring)
    return LongitudinalEvidencePack(
        subject=subject,
        diagnosis_report_count=len(
            {item.diagnosis_report_id for item in evidence_items}
        ),
        question_count=len(evidence_items),
        evidence_index=evidence_index,
        recurring_gaps=recurring,
        broader_patterns=validated_patterns,
    )


class LiteLLMLocalGapClassifier:
    def __init__(
        self,
        *,
        model_config: SemanticClusterModelConfig | None = None,
        completion_fn=completion,
    ):
        self.model_config = model_config or SemanticClusterModelConfig()
        self.completion_fn = completion_fn

    def classify(self, *, evidence_items, candidates) -> list[LocalConceptGap]:
        config = self.model_config.resolve()
        kwargs = config.to_litellm_kwargs()
        kwargs.setdefault("num_retries", 0)
        response = self.completion_fn(
            **kwargs,
            messages=[
                {"role": "system", "content": _local_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "evidence": [
                                _evidence_payload(item) for item in evidence_items
                            ],
                            "candidates": [
                                candidate.model_dump() for candidate in candidates
                            ],
                        },
                        sort_keys=True,
                    ),
                },
            ],
            response_format=_response_format(
                "student_profile_local_concept_gaps",
                LocalConceptGapOutput,
            ),
            caching=False,
            cache={"no-cache": True},
        )
        return LocalConceptGapOutput.model_validate_json(
            response["choices"][0]["message"]["content"].strip()
        ).gaps


class LiteLLMBroaderPatternClassifier:
    def __init__(
        self,
        *,
        model_config: SemanticClusterModelConfig | None = None,
        completion_fn=completion,
    ):
        self.model_config = model_config or SemanticClusterModelConfig()
        self.completion_fn = completion_fn

    def classify(self, *, recurring_gaps, candidates) -> list[BroaderConceptualPattern]:
        config = self.model_config.resolve()
        kwargs = config.to_litellm_kwargs()
        kwargs.setdefault("num_retries", 0)
        response = self.completion_fn(
            **kwargs,
            messages=[
                {"role": "system", "content": _broader_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "recurring_gaps": [
                                item.model_dump() for item in recurring_gaps
                            ],
                            "candidates": [
                                candidate.model_dump() for candidate in candidates
                            ],
                        },
                        sort_keys=True,
                    ),
                },
            ],
            response_format=_response_format(
                "student_profile_broader_patterns",
                BroaderPatternOutput,
            ),
            caching=False,
            cache={"no-cache": True},
        )
        return BroaderPatternOutput.model_validate_json(
            response["choices"][0]["message"]["content"].strip()
        ).patterns


def _local_system_prompt() -> str:
    return (
        "Classify JEE diagnosis evidence into precise local concept gaps within the supplied "
        "chapter/topic context. A gap is exact only when all evidence requires the same "
        "concept, shows the same or equivalent misconception, and is corrected by one "
        "targeted explanation. Split broad candidates. Do not convert arithmetic, careless "
        "execution, or prompt-reading errors into concept gaps. Preserve evidence ids and "
        "return strict JSON only."
    )


def _broader_system_prompt() -> str:
    return (
        "Identify broader conceptual-reasoning patterns across validated recurring local "
        "gaps from different chapter/topic contexts. A pattern must name the common reasoning "
        "failure and common corrective principle while preserving each local manifestation. "
        "Do not group by vocabulary, syllabus proximity, calculation slips, or generic study "
        "behavior. Preserve component gap ids and return strict JSON only."
    )


def _response_format(name: str, model: type[BaseModel]) -> dict[str, object]:
    schema = deepcopy(model.model_json_schema())
    schema["additionalProperties"] = False
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "schema": schema, "strict": True},
    }


def _evidence_payload(item: ProfileEvidenceItem) -> dict[str, str]:
    return {
        "evidence_id": item.evidence_id,
        "diagnosis_report_id": item.diagnosis_report_id,
        "chapter": item.canonical_chapter,
        "topic": item.canonical_topic,
        "exact_concept_gap": item.exact_concept_gap,
        "likely_thought": item.likely_thought,
        "why_wrong": item.why_wrong,
        "deep_dive_recommendation": item.deep_dive_recommendation,
    }


def _gap_as_evidence(
    gap: LocalConceptGap,
    evidence_index: dict[str, ProfileEvidenceItem],
) -> ProfileEvidenceItem:
    source = evidence_index[gap.evidence_ids[0]]
    return ProfileEvidenceItem(
        evidence_id=gap.gap_id,
        evidence_reference=gap.gap_id,
        diagnosis_report_id=f"local-gap:{gap.gap_id}",
        diagnosis_json_s3_uri=source.diagnosis_json_s3_uri,
        subject=source.subject,
        test_name="local-gap-synthesis",
        test_date=None,
        test_date_source="unavailable",
        diagnosis_date=source.diagnosis_date,
        question_number=gap.gap_id,
        chapter=gap.canonical_chapter,
        topic=gap.canonical_topic,
        canonical_chapter=gap.canonical_chapter,
        canonical_topic=gap.canonical_topic,
        exact_concept_gap=gap.concept_gap,
        likely_thought=gap.shared_misconception,
        why_wrong=gap.rationale,
        deep_dive_recommendation=gap.corrective_concept,
    )


def _location(gap: LocalConceptGap) -> tuple[str, str]:
    return gap.canonical_chapter.casefold(), gap.canonical_topic.casefold()


def _gap_by_id(
    gaps: list[ValidatedRecurringGap],
    gap_id: str,
) -> ValidatedRecurringGap:
    return next(item for item in gaps if item.gap.gap_id == gap_id)
