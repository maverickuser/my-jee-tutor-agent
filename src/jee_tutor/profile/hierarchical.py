from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
import logging
import re
from typing import Literal, Protocol

from litellm import completion
from pydantic import BaseModel, ConfigDict, Field, field_validator

from jee_tutor.profile.clustering import (
    EvidenceNeighborPair,
    build_mutual_neighbor_pairs,
)
from jee_tutor.profile.embeddings import (
    EvidenceEmbeddingRecord,
    EvidenceEmbeddingService,
)
from jee_tutor.profile.evidence import ProfileEvidenceItem
from jee_tutor.profile.model_config import ProfileClassifierModelConfig
from jee_tutor.agent.observability import (
    LangfuseObservability,
    safe_provider_response_metadata,
)
from jee_tutor.model_routing import is_gemini_36_model


logger = logging.getLogger(__name__)


Confidence = Literal["high", "medium", "low"]
RelationshipType = Literal[
    "same_underlying_gap",
    "related_but_distinct",
    "unrelated",
    "non_conceptual",
]
ExclusionReason = Literal[
    "calculation_execution",
    "ambiguous_question",
    "insufficient_evidence",
    "unrelated_misconception",
]


class StrandManifestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    manifestation: str = Field(min_length=1)


class EvidenceExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    reason: ExclusionReason
    rationale: str = Field(min_length=1)


class CandidateRelationshipDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_pair_id: str = Field(min_length=1)
    relationship: RelationshipType
    rationale: str = Field(min_length=1)


class ConceptualStrand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strand_id: str = Field(min_length=1)
    chapter_family: str = Field(min_length=1)
    chapter_labels: list[str] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    title: str = Field(min_length=1)
    missing_mental_model: str = Field(min_length=1)
    shared_failure: str = Field(min_length=1)
    corrective_model: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    manifestations: list[StrandManifestation] = Field(min_length=1)
    confidence: Confidence
    rationale: str = Field(min_length=1)

    @field_validator("chapter_labels", "topics", "evidence_ids")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Conceptual strand contains duplicate values.")
        return value


class ConceptualStrandOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationships: list[CandidateRelationshipDecision] = Field(
        default_factory=list
    )
    strands: list[ConceptualStrand] = Field(default_factory=list)
    exclusions: list[EvidenceExclusion] = Field(default_factory=list)


class ValidatedRecurringStrand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strand: ConceptualStrand
    diagnosis_report_count: int = Field(ge=2)
    question_count: int = Field(ge=2)


class ConceptualStrandClassifier(Protocol):
    def classify(
        self,
        *,
        evidence_items: list[ProfileEvidenceItem],
        candidate_pairs: list[EvidenceNeighborPair],
    ) -> ConceptualStrandOutput: ...


class ConceptualStrandAnalyzer:
    def __init__(
        self,
        *,
        embedding_service: EvidenceEmbeddingService | None = None,
        classifier: ConceptualStrandClassifier | None = None,
        analyzer: Callable[[list[ProfileEvidenceItem]], ConceptualStrandOutput]
        | None = None,
        similarity_floor: float = 0.68,
        max_neighbors: int = 3,
    ):
        self.embedding_service = embedding_service
        self.classifier = classifier
        self.analyzer = analyzer
        self.similarity_floor = similarity_floor
        self.max_neighbors = max_neighbors

    def analyze(
        self,
        evidence_items: list[ProfileEvidenceItem],
        *,
        subject: str,
    ) -> ConceptualStrandOutput:
        if self.analyzer is not None:
            return validate_conceptual_strand_output(
                repair_conceptual_strand_output(
                    self.analyzer(evidence_items), evidence_items
                ),
                evidence_items,
            )
        embedding_service = self.embedding_service or EvidenceEmbeddingService(
            input_version="conceptual-strand-v2"
        )
        records = embedding_service.ensure_embeddings(
            subject=subject,
            evidence_items=evidence_items,
        )
        candidate_pairs = build_strand_candidate_pairs(
            evidence_items=evidence_items,
            embedding_records=records,
            similarity_floor=self.similarity_floor,
            max_neighbors=self.max_neighbors,
        )
        classifier = self.classifier or LiteLLMConceptualStrandClassifier()
        classified = classifier.classify(
            evidence_items=evidence_items,
            candidate_pairs=candidate_pairs,
        )
        validate_candidate_relationships(
            classified.relationships,
            candidate_pairs,
        )
        repaired = repair_conceptual_strand_output(
            classified,
            evidence_items,
            candidate_pairs=candidate_pairs,
        )
        supported = discard_unsupported_strands(
            repaired,
            candidate_pairs=candidate_pairs,
        )
        return validate_conceptual_strand_output(
            supported,
            evidence_items,
            candidate_pairs=candidate_pairs,
        )


def normalize_chapter_family(chapter: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", chapter.casefold()).strip()
    if "electrostatic" in normalized or "capacitan" in normalized:
        return "Electrostatics and Capacitance"
    if "electromagnetic induction" in normalized:
        return "Electromagnetic Induction"
    if "magnetic effect" in normalized or normalized in {
        "magnetism",
        "magnetism and matter",
    }:
        return "Magnetic Effects and Magnetism"
    if "current electricity" in normalized:
        return "Current Electricity"
    return " ".join(word.capitalize() for word in normalized.split())


def build_strand_candidate_pairs(
    *,
    evidence_items: list[ProfileEvidenceItem],
    embedding_records: dict[str, EvidenceEmbeddingRecord],
    similarity_floor: float,
    max_neighbors: int,
) -> list[EvidenceNeighborPair]:
    grouped: dict[str, list[ProfileEvidenceItem]] = {}
    for item in evidence_items:
        grouped.setdefault(
            normalize_chapter_family(item.canonical_chapter),
            [],
        ).append(item)
    pairs: list[EvidenceNeighborPair] = []
    for family in sorted(grouped):
        family_items = grouped[family]
        pairs.extend(
            build_mutual_neighbor_pairs(
                evidence_items=family_items,
                embedding_records=embedding_records,
                chapter_family=family,
                similarity_floor=similarity_floor,
                max_neighbors=max_neighbors,
            )
        )
    return pairs


def validate_conceptual_strand_output(
    output: ConceptualStrandOutput,
    evidence_items: list[ProfileEvidenceItem],
    *,
    candidate_pairs: list[EvidenceNeighborPair] | None = None,
) -> ConceptualStrandOutput:
    if candidate_pairs is not None:
        validate_candidate_relationships(
            output.relationships,
            candidate_pairs,
        )
    index = {item.evidence_id: item for item in evidence_items}
    assigned: set[str] = set()
    for strand in output.strands:
        unknown = set(strand.evidence_ids) - set(index)
        if unknown:
            raise ValueError(
                f"Conceptual strand references unknown evidence ids: {sorted(unknown)}"
            )
        families = {
            normalize_chapter_family(index[evidence_id].canonical_chapter)
            for evidence_id in strand.evidence_ids
        }
        if len(families) != 1 or strand.chapter_family.casefold() != next(
            iter(families)
        ).casefold():
            raise ValueError("Conceptual strand spans multiple chapter families.")
        manifestation_ids = [item.evidence_id for item in strand.manifestations]
        if len(manifestation_ids) != len(set(manifestation_ids)):
            raise ValueError("Conceptual strand contains duplicate manifestations.")
        if set(manifestation_ids) != set(strand.evidence_ids):
            raise ValueError(
                "Conceptual strand manifestations must exactly cover evidence ids."
            )
        if assigned.intersection(strand.evidence_ids):
            raise ValueError("Evidence is assigned to multiple conceptual strands.")
        if candidate_pairs is not None and len(strand.evidence_ids) > 1:
            _validate_strand_relationship_support(
                strand,
                output.relationships,
                candidate_pairs,
            )
        assigned.update(strand.evidence_ids)
    exclusion_ids = [item.evidence_id for item in output.exclusions]
    if len(exclusion_ids) != len(set(exclusion_ids)):
        raise ValueError("Evidence is excluded more than once.")
    if set(exclusion_ids) - set(index):
        raise ValueError("Evidence exclusion references an unknown evidence id.")
    if assigned.intersection(exclusion_ids):
        raise ValueError("Evidence cannot be both assigned and excluded.")
    return output


def repair_conceptual_strand_output(
    output: ConceptualStrandOutput,
    evidence_items: list[ProfileEvidenceItem],
    *,
    candidate_pairs: list[EvidenceNeighborPair] | None = None,
) -> ConceptualStrandOutput:
    index = {item.evidence_id: item for item in evidence_items}
    assigned: set[str] = set()
    repaired_strands: list[ConceptualStrand] = []
    for source_strand in output.strands:
        strand = source_strand.model_copy(deep=True)
        known_ids = [
            evidence_id
            for evidence_id in strand.evidence_ids
            if evidence_id in index and evidence_id not in assigned
        ]
        if not known_ids:
            continue
        family_by_id = {
            evidence_id: normalize_chapter_family(
                index[evidence_id].canonical_chapter
            )
            for evidence_id in known_ids
        }
        declared_family = normalize_chapter_family(strand.chapter_family)
        retained_ids = [
            evidence_id
            for evidence_id in known_ids
            if family_by_id[evidence_id].casefold()
            == declared_family.casefold()
        ]
        if retained_ids:
            chosen_family = declared_family
        else:
            family_counts: dict[str, int] = {}
            for evidence_id in known_ids:
                family = family_by_id[evidence_id]
                family_counts[family] = family_counts.get(family, 0) + 1
            chosen_family = max(
                family_counts,
                key=lambda family: (
                    family_counts[family],
                    -known_ids.index(
                        next(
                            evidence_id
                            for evidence_id in known_ids
                            if family_by_id[evidence_id] == family
                        )
                    ),
                ),
            )
            retained_ids = [
                evidence_id
                for evidence_id in known_ids
                if family_by_id[evidence_id] == chosen_family
            ]
        manifestation_by_id = {
            item.evidence_id: item.manifestation
            for item in strand.manifestations
            if item.evidence_id in retained_ids
        }
        strand.chapter_family = chosen_family
        strand.chapter_labels = _unique_strings(
            index[evidence_id].canonical_chapter
            for evidence_id in retained_ids
        )
        strand.topics = _unique_strings(
            index[evidence_id].canonical_topic
            for evidence_id in retained_ids
        )
        strand.evidence_ids = retained_ids
        strand.manifestations = [
            StrandManifestation(
                evidence_id=evidence_id,
                manifestation=manifestation_by_id.get(evidence_id)
                or index[evidence_id].exact_concept_gap,
            )
            for evidence_id in retained_ids
        ]
        assigned.update(retained_ids)
        repaired_strands.append(strand)
    repaired_exclusions: list[EvidenceExclusion] = []
    excluded: set[str] = set()
    for exclusion in output.exclusions:
        if (
            exclusion.evidence_id not in index
            or exclusion.evidence_id in assigned
            or exclusion.evidence_id in excluded
        ):
            continue
        repaired_exclusions.append(exclusion)
        excluded.add(exclusion.evidence_id)
    return ConceptualStrandOutput(
        relationships=_ordered_relationships(
            output.relationships,
            candidate_pairs,
        ),
        strands=repaired_strands,
        exclusions=repaired_exclusions,
    )


def validate_candidate_relationships(
    relationships: list[CandidateRelationshipDecision],
    candidate_pairs: list[EvidenceNeighborPair],
) -> list[CandidateRelationshipDecision]:
    expected_pair_ids = {pair.pair_id for pair in candidate_pairs}
    relationship_ids = [
        relationship.candidate_pair_id for relationship in relationships
    ]
    if len(relationship_ids) != len(set(relationship_ids)):
        raise ValueError("Candidate relationship decisions contain duplicate pair ids.")
    invented = set(relationship_ids) - expected_pair_ids
    if invented:
        raise ValueError(
            f"Candidate relationship decisions reference unknown pair ids: "
            f"{sorted(invented)}"
        )
    missing = expected_pair_ids - set(relationship_ids)
    if missing:
        raise ValueError(
            f"Candidate relationship decisions are missing pair ids: "
            f"{sorted(missing)}"
        )
    return relationships


def _ordered_relationships(
    relationships: list[CandidateRelationshipDecision],
    candidate_pairs: list[EvidenceNeighborPair] | None,
) -> list[CandidateRelationshipDecision]:
    if candidate_pairs is None:
        return list(relationships)
    by_pair_id = {
        relationship.candidate_pair_id: relationship
        for relationship in relationships
    }
    return [
        by_pair_id[pair.pair_id]
        for pair in candidate_pairs
        if pair.pair_id in by_pair_id
    ]


def _validate_strand_relationship_support(
    strand: ConceptualStrand,
    relationships: list[CandidateRelationshipDecision],
    candidate_pairs: list[EvidenceNeighborPair],
) -> None:
    relationship_by_pair_id = {
        relationship.candidate_pair_id: relationship.relationship
        for relationship in relationships
    }
    strand_evidence_ids = set(strand.evidence_ids)
    same_gap_adjacency = {
        evidence_id: set() for evidence_id in strand.evidence_ids
    }
    for pair in candidate_pairs:
        pair_evidence_ids = {
            pair.left_evidence_id,
            pair.right_evidence_id,
        }
        if not pair_evidence_ids.issubset(strand_evidence_ids):
            continue
        relationship = relationship_by_pair_id[pair.pair_id]
        if relationship != "same_underlying_gap":
            raise ValueError(
                "Conceptual strand contains a contradictory internal "
                "candidate relationship."
            )
        same_gap_adjacency[pair.left_evidence_id].add(
            pair.right_evidence_id
        )
        same_gap_adjacency[pair.right_evidence_id].add(
            pair.left_evidence_id
        )

    reachable: set[str] = set()
    pending = [strand.evidence_ids[0]]
    while pending:
        evidence_id = pending.pop()
        if evidence_id in reachable:
            continue
        reachable.add(evidence_id)
        pending.extend(same_gap_adjacency[evidence_id] - reachable)
    if reachable != strand_evidence_ids:
        raise ValueError(
            "Conceptual strand is not connected by same-underlying-gap "
            "candidate relationships."
        )


def discard_unsupported_strands(
    output: ConceptualStrandOutput,
    *,
    candidate_pairs: list[EvidenceNeighborPair],
) -> ConceptualStrandOutput:
    """Drop LLM strands that contradict their validated pair relationships."""
    supported: list[ConceptualStrand] = []
    for strand in output.strands:
        if len(strand.evidence_ids) < 2:
            supported.append(strand)
            continue
        try:
            _validate_strand_relationship_support(
                strand,
                output.relationships,
                candidate_pairs,
            )
        except ValueError as exc:
            logger.warning(
                "profile_strand_dropped strand_id=%s reason=%s evidence_count=%s",
                strand.strand_id,
                _strand_drop_reason(exc),
                len(strand.evidence_ids),
            )
            continue
        supported.append(strand)
    return output.model_copy(update={"strands": supported})


def _strand_drop_reason(exc: ValueError) -> str:
    if "contradictory internal" in str(exc):
        return "contradictory_internal_relationship"
    return "disconnected_same_gap_graph"


def recurring_conceptual_strands(
    strands: list[ConceptualStrand],
    evidence_index: dict[str, ProfileEvidenceItem],
) -> list[ValidatedRecurringStrand]:
    recurring: list[ValidatedRecurringStrand] = []
    for strand in strands:
        report_ids = {
            evidence_index[evidence_id].diagnosis_report_id
            for evidence_id in strand.evidence_ids
        }
        if len(report_ids) < 2 or strand.confidence == "low":
            continue
        recurring.append(
            ValidatedRecurringStrand(
                strand=strand,
                diagnosis_report_count=len(report_ids),
                question_count=len(strand.evidence_ids),
            )
        )
    return recurring


class LiteLLMConceptualStrandClassifier:
    def __init__(
        self,
        *,
        model_config: ProfileClassifierModelConfig | None = None,
        observability: LangfuseObservability | None = None,
        completion_fn=completion,
    ):
        self.model_config = model_config or ProfileClassifierModelConfig()
        self.observability = observability or LangfuseObservability()
        self.completion_fn = completion_fn

    def classify(
        self,
        *,
        evidence_items,
        candidate_pairs,
    ) -> ConceptualStrandOutput:
        config = self.model_config.resolve()
        kwargs = config.to_litellm_kwargs()
        if not is_gemini_36_model(config.model):
            kwargs["temperature"] = 0
        kwargs.setdefault("num_retries", 0)
        messages = [
            {"role": "system", "content": _strand_system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "evidence": [_evidence_payload(item) for item in evidence_items],
                        "candidate_pairs": [
                            pair.model_dump() for pair in candidate_pairs
                        ],
                    },
                    sort_keys=True,
                ),
            },
        ]
        with self.observability.generation_span(
            name="profile-conceptual-strand-classification",
            model=config.model,
            input_payload={
                "evidence_count": len(evidence_items),
                "candidate_pair_count": len(candidate_pairs),
                "candidate_pair_ids": [pair.pair_id for pair in candidate_pairs],
            },
            metadata={
                "task": "profile",
                "output_format": "json_schema",
                "schema_name": "student_profile_conceptual_strands",
                "temperature": None if is_gemini_36_model(config.model) else 0,
            },
        ) as generation:
            try:
                response = self.completion_fn(
                    **kwargs,
                    messages=messages,
                    response_format=_response_format(
                        "student_profile_conceptual_strands",
                        ConceptualStrandOutput,
                    ),
                    caching=False,
                    cache={"no-cache": True},
                )
                result = ConceptualStrandOutput.model_validate_json(
                    response["choices"][0]["message"]["content"].strip()
                )
            except Exception as exc:
                if generation:
                    generation.update(
                        output={
                            "validation_status": "failed",
                            "error_type": exc.__class__.__name__,
                        }
                    )
                raise
            if generation:
                update = {
                    "output": {
                        "validation_status": "passed",
                        "relationship_count": len(result.relationships),
                        "strand_count": len(result.strands),
                        "exclusion_count": len(result.exclusions),
                    },
                    **_profile_generation_usage(response),
                }
                response_metadata = safe_provider_response_metadata(response)
                if response_metadata:
                    update["metadata"] = response_metadata
                generation.update(**update)
            return result


def _profile_generation_usage(response: object) -> dict[str, dict[str, int | float]]:
    usage = (
        response.get("usage")
        if isinstance(response, dict)
        else getattr(response, "usage", None)
    )
    values = (
        usage
        if isinstance(usage, dict)
        else usage.model_dump(exclude_none=True)
        if usage
        else {}
    )
    aliases = {
        "prompt_tokens": "input",
        "completion_tokens": "output",
        "total_tokens": "total",
    }
    details = {
        target: int(values[source])
        for source, target in aliases.items()
        if isinstance(values.get(source), int)
    }
    accounting: dict[str, dict[str, int | float]] = {}
    if details:
        accounting["usage_details"] = details
    hidden = (
        response.get("_hidden_params")
        if isinstance(response, dict)
        else getattr(response, "_hidden_params", None)
    )
    if isinstance(hidden, dict) and isinstance(hidden.get("response_cost"), int | float):
        accounting["cost_details"] = {"total": float(hidden["response_cost"])}
    return accounting


def _strand_system_prompt() -> str:
    return (
        "You are an expert JEE educational diagnostician and cognitive learning specialist. "
        "Your task is to synthesize precise conceptual strands from JEE question diagnoses. "
        "First classify "
        "every supplied candidate pair exactly once as same_underlying_gap, "
        "related_but_distinct, unrelated, or non_conceptual, with a specific rationale. "
        "A strand is one missing mental model or conceptual operation within the pair's "
        "chapter family. Every multi-evidence strand must be connected through candidate "
        "pairs classified as same_underlying_gap; never place a related-but-distinct, "
        "unrelated, or non-conceptual internal pair in one strand. Different topic labels "
        "and question symptoms may belong together only when one coherent corrective model "
        "fixes every item. For each evidence id, state its distinct manifestation of the "
        "shared gap. Do not create strands from arithmetic execution, ambiguous questions, "
        "generic formula recall, carelessness, shared vocabulary, or syllabus proximity. "
        "Use exclusions for non-conceptual or unsupported evidence. Preserve all evidence "
        "and candidate pair ids exactly and return strict JSON only."
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
        "chapter_family": normalize_chapter_family(item.canonical_chapter),
        "topic": item.canonical_topic,
        "exact_concept_gap": item.exact_concept_gap,
        "likely_thought": item.likely_thought,
        "why_wrong": item.why_wrong,
        "deep_dive_recommendation": item.deep_dive_recommendation,
    }


def _unique_strings(values) -> list[str]:
    return list(dict.fromkeys(values))
