from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
import re
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

    strands: list[ConceptualStrand] = Field(default_factory=list)
    exclusions: list[EvidenceExclusion] = Field(default_factory=list)


class ValidatedRecurringStrand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strand: ConceptualStrand
    diagnosis_report_count: int = Field(ge=2)
    question_count: int = Field(ge=2)


class BroaderPatternManifestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strand_id: str = Field(min_length=1)
    chapter_family: str = Field(min_length=1)
    manifestation: str = Field(min_length=1)


class BroaderConceptualPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    shared_reasoning_gap: str = Field(min_length=1)
    common_corrective_principle: str = Field(min_length=1)
    component_strand_ids: list[str] = Field(min_length=2)
    manifestations: list[BroaderPatternManifestation] = Field(min_length=2)
    confidence: Confidence
    rationale: str = Field(min_length=1)

    @field_validator("component_strand_ids")
    @classmethod
    def unique_components(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Broader pattern contains duplicate component strands.")
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
    recurring_strands: list[ValidatedRecurringStrand] = Field(default_factory=list)
    broader_patterns: list[BroaderConceptualPattern] = Field(default_factory=list)
    exclusions: list[EvidenceExclusion] = Field(default_factory=list)


class ConceptualStrandClassifier(Protocol):
    def classify(
        self,
        *,
        evidence_items: list[ProfileEvidenceItem],
        candidates: list[SemanticCandidateCluster],
    ) -> ConceptualStrandOutput: ...


class BroaderPatternClassifier(Protocol):
    def classify(
        self,
        *,
        recurring_strands: list[ValidatedRecurringStrand],
        candidates: list[SemanticCandidateCluster],
    ) -> list[BroaderConceptualPattern]: ...


class ConceptualStrandAnalyzer:
    def __init__(
        self,
        *,
        embedding_service: EvidenceEmbeddingService | None = None,
        classifier: ConceptualStrandClassifier | None = None,
        analyzer: Callable[[list[ProfileEvidenceItem]], ConceptualStrandOutput]
        | None = None,
        similarity_threshold: float = 0.68,
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
    ) -> ConceptualStrandOutput:
        if self.analyzer is not None:
            return validate_conceptual_strand_output(
                repair_conceptual_strand_output(
                    self.analyzer(evidence_items), evidence_items
                ),
                evidence_items,
            )
        embedding_service = self.embedding_service or EvidenceEmbeddingService(
            input_version="conceptual-strand-v1"
        )
        records = embedding_service.ensure_embeddings(
            subject=subject,
            evidence_items=evidence_items,
        )
        candidates = build_strand_candidate_clusters(
            evidence_items=evidence_items,
            embedding_records=records,
            similarity_threshold=self.similarity_threshold,
        )
        classifier = self.classifier or LiteLLMConceptualStrandClassifier()
        return validate_conceptual_strand_output(
            repair_conceptual_strand_output(
                classifier.classify(
                    evidence_items=evidence_items,
                    candidates=candidates,
                ),
                evidence_items,
            ),
            evidence_items,
        )


class BroaderPatternAnalyzer:
    def __init__(
        self,
        *,
        embedding_service: EvidenceEmbeddingService | None = None,
        classifier: BroaderPatternClassifier | None = None,
        analyzer: Callable[
            [list[ValidatedRecurringStrand]], list[BroaderConceptualPattern]
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
        recurring_strands: list[ValidatedRecurringStrand],
        *,
        evidence_index: dict[str, ProfileEvidenceItem],
        subject: str,
    ) -> list[BroaderConceptualPattern]:
        if len({item.strand.chapter_family.casefold() for item in recurring_strands}) < 2:
            return []
        if self.analyzer is not None:
            return validate_broader_patterns(
                self.analyzer(recurring_strands), recurring_strands
            )
        synthetic = [
            _strand_as_evidence(item.strand, evidence_index)
            for item in recurring_strands
        ]
        embedding_service = self.embedding_service or EvidenceEmbeddingService(
            input_version="recurring-strand-v1"
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
                    _strand_by_id(recurring_strands, strand_id)
                    .strand.chapter_family.casefold()
                    for strand_id in candidate.evidence_ids
                }
            )
            >= 2
        ]
        if not candidates:
            return []
        classifier = self.classifier or LiteLLMBroaderPatternClassifier()
        return validate_broader_patterns(
            classifier.classify(
                recurring_strands=recurring_strands,
                candidates=candidates,
            ),
            recurring_strands,
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


def build_strand_candidate_clusters(
    *,
    evidence_items: list[ProfileEvidenceItem],
    embedding_records,
    similarity_threshold: float,
) -> list[SemanticCandidateCluster]:
    grouped: dict[str, list[ProfileEvidenceItem]] = {}
    for item in evidence_items:
        grouped.setdefault(
            normalize_chapter_family(item.canonical_chapter),
            [],
        ).append(item)
    candidates: list[SemanticCandidateCluster] = []
    for family_index, (family, items) in enumerate(grouped.items(), start=1):
        local = build_embedding_candidate_clusters(
            evidence_items=items,
            embedding_records={
                item.evidence_id: embedding_records[item.evidence_id] for item in items
            },
            similarity_threshold=similarity_threshold,
        )
        for candidate_index, candidate in enumerate(local, start=1):
            candidate.candidate_id = (
                f"family-{family_index}-candidate-{candidate_index}"
            )
            candidate.rationale = (
                f"Chapter family: {family}. {candidate.rationale}"
            )
            candidates.append(candidate)
    return candidates


def validate_conceptual_strand_output(
    output: ConceptualStrandOutput,
    evidence_items: list[ProfileEvidenceItem],
) -> ConceptualStrandOutput:
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
        strands=repaired_strands,
        exclusions=repaired_exclusions,
    )


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


def validate_broader_patterns(
    patterns: list[BroaderConceptualPattern],
    recurring_strands: list[ValidatedRecurringStrand],
) -> list[BroaderConceptualPattern]:
    strand_index = {
        item.strand.strand_id: item for item in recurring_strands
    }
    for pattern in patterns:
        unknown = set(pattern.component_strand_ids) - set(strand_index)
        if unknown:
            raise ValueError(
                f"Broader pattern references unknown strand ids: {sorted(unknown)}"
            )
        families = {
            strand_index[strand_id].strand.chapter_family.casefold()
            for strand_id in pattern.component_strand_ids
        }
        if len(families) < 2:
            raise ValueError("Broader pattern must span distinct chapter families.")
        if pattern.confidence == "low":
            raise ValueError("Low-confidence broader patterns are not reportable.")
        if {item.strand_id for item in pattern.manifestations} != set(
            pattern.component_strand_ids
        ):
            raise ValueError(
                "Broader pattern manifestations must cover component strands."
            )
    return patterns


def build_longitudinal_evidence_pack(
    *,
    subject: str,
    evidence_items: list[ProfileEvidenceItem],
    strand_output: ConceptualStrandOutput,
    broader_patterns: list[BroaderConceptualPattern],
) -> LongitudinalEvidencePack:
    evidence_index = {item.evidence_id: item for item in evidence_items}
    recurring = recurring_conceptual_strands(
        strand_output.strands, evidence_index
    )
    validated_patterns = validate_broader_patterns(
        broader_patterns, recurring
    )
    return LongitudinalEvidencePack(
        subject=subject,
        diagnosis_report_count=len(
            {item.diagnosis_report_id for item in evidence_items}
        ),
        question_count=len(evidence_items),
        evidence_index=evidence_index,
        recurring_strands=recurring,
        broader_patterns=validated_patterns,
        exclusions=strand_output.exclusions,
    )


class LiteLLMConceptualStrandClassifier:
    def __init__(
        self,
        *,
        model_config: SemanticClusterModelConfig | None = None,
        completion_fn=completion,
    ):
        self.model_config = model_config or SemanticClusterModelConfig()
        self.completion_fn = completion_fn

    def classify(self, *, evidence_items, candidates) -> ConceptualStrandOutput:
        config = self.model_config.resolve()
        kwargs = config.to_litellm_kwargs()
        kwargs.setdefault("num_retries", 0)
        response = self.completion_fn(
            **kwargs,
            messages=[
                {"role": "system", "content": _strand_system_prompt()},
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
                "student_profile_conceptual_strands",
                ConceptualStrandOutput,
            ),
            caching=False,
            cache={"no-cache": True},
        )
        return ConceptualStrandOutput.model_validate_json(
            response["choices"][0]["message"]["content"].strip()
        )


class LiteLLMBroaderPatternClassifier:
    def __init__(
        self,
        *,
        model_config: SemanticClusterModelConfig | None = None,
        completion_fn=completion,
    ):
        self.model_config = model_config or SemanticClusterModelConfig()
        self.completion_fn = completion_fn

    def classify(
        self, *, recurring_strands, candidates
    ) -> list[BroaderConceptualPattern]:
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
                            "recurring_strands": [
                                item.model_dump() for item in recurring_strands
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


def _strand_system_prompt() -> str:
    return (
        "Synthesize precise conceptual strands from JEE question diagnoses. A strand is "
        "one missing mental model or conceptual operation within the chapter family named "
        "in each candidate. Different topic labels and question symptoms may belong "
        "together only when one coherent corrective model fixes every item. You may merge "
        "embedding candidates inside the same family, split them, or exclude evidence. "
        "For each evidence id, state its distinct manifestation of the shared gap. Do not "
        "create strands from arithmetic execution, ambiguous questions, generic formula "
        "recall, carelessness, shared vocabulary, or syllabus proximity. Use exclusions "
        "for non-conceptual or unsupported evidence. Preserve evidence ids and return "
        "strict JSON only."
    )


def _broader_system_prompt() -> str:
    return (
        "Identify broader conceptual-reasoning patterns across validated recurring "
        "conceptual strands from distinct chapter families. A pattern must name a precise "
        "transferable reasoning failure and common corrective principle while preserving "
        "each strand's distinct manifestation. Reject generic labels such as formula "
        "recall, carelessness, calculation mistakes, vocabulary overlap, or syllabus "
        "proximity. Preserve component strand ids and return strict JSON only."
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


def _strand_as_evidence(
    strand: ConceptualStrand,
    evidence_index: dict[str, ProfileEvidenceItem],
) -> ProfileEvidenceItem:
    source = evidence_index[strand.evidence_ids[0]]
    return ProfileEvidenceItem(
        evidence_id=strand.strand_id,
        evidence_reference=strand.strand_id,
        diagnosis_report_id=f"conceptual-strand:{strand.strand_id}",
        diagnosis_json_s3_uri=source.diagnosis_json_s3_uri,
        subject=source.subject,
        test_name="conceptual-strand-synthesis",
        test_date=None,
        test_date_source="unavailable",
        diagnosis_date=source.diagnosis_date,
        question_number=strand.strand_id,
        chapter=strand.chapter_family,
        topic=strand.title,
        canonical_chapter=strand.chapter_family,
        canonical_topic=strand.title,
        exact_concept_gap=strand.missing_mental_model,
        likely_thought=strand.shared_failure,
        why_wrong=strand.rationale,
        deep_dive_recommendation=strand.corrective_model,
    )


def _strand_by_id(
    strands: list[ValidatedRecurringStrand],
    strand_id: str,
) -> ValidatedRecurringStrand:
    return next(
        item for item in strands if item.strand.strand_id == strand_id
    )


def _unique_strings(values) -> list[str]:
    return list(dict.fromkeys(values))
