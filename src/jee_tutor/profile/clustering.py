from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from math import sqrt

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jee_tutor.profile.embeddings import EvidenceEmbeddingRecord
from jee_tutor.profile.evidence import ProfileEvidenceItem


class EvidenceNeighborPair(BaseModel):
    """A deterministic reciprocal-neighbor candidate for LLM adjudication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pair_id: str = Field(min_length=1)
    left_evidence_id: str = Field(min_length=1)
    right_evidence_id: str = Field(min_length=1)
    chapter_family: str = Field(min_length=1)
    cosine_similarity: float = Field(ge=-1.0, le=1.0)
    left_neighbor_rank: int = Field(ge=1)
    right_neighbor_rank: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_canonical_pair(self) -> "EvidenceNeighborPair":
        if self.left_evidence_id >= self.right_evidence_id:
            raise ValueError(
                "Neighbor pair evidence ids must be distinct and lexically ordered."
            )
        return self


def build_mutual_neighbor_pairs(
    *,
    evidence_items: list[ProfileEvidenceItem],
    embedding_records: Mapping[str, EvidenceEmbeddingRecord],
    chapter_family: str,
    similarity_floor: float,
    max_neighbors: int,
) -> list[EvidenceNeighborPair]:
    """Return reciprocal top-k pairs above an absolute cosine-similarity floor."""

    if max_neighbors < 1:
        raise ValueError("max_neighbors must be at least 1.")
    if not -1.0 <= similarity_floor <= 1.0:
        raise ValueError("similarity_floor must be between -1 and 1.")

    evidence_ids = sorted(item.evidence_id for item in evidence_items)
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("Evidence items must have unique evidence ids.")
    missing = set(evidence_ids) - set(embedding_records)
    if missing:
        raise ValueError(f"Missing embeddings for evidence ids: {sorted(missing)}")

    similarities = _pairwise_similarities(evidence_ids, embedding_records)
    ranks = _neighbor_ranks(evidence_ids, similarities)
    pairs: list[EvidenceNeighborPair] = []
    for left_index, left_id in enumerate(evidence_ids):
        for right_id in evidence_ids[left_index + 1 :]:
            similarity = similarities[(left_id, right_id)]
            left_rank = ranks[left_id][right_id]
            right_rank = ranks[right_id][left_id]
            if (
                similarity < similarity_floor
                or left_rank > max_neighbors
                or right_rank > max_neighbors
            ):
                continue
            pairs.append(
                EvidenceNeighborPair(
                    pair_id=_pair_id(left_id, right_id),
                    left_evidence_id=left_id,
                    right_evidence_id=right_id,
                    chapter_family=chapter_family,
                    cosine_similarity=similarity,
                    left_neighbor_rank=left_rank,
                    right_neighbor_rank=right_rank,
                )
            )
    return pairs


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding vectors must have the same dimensions.")
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    similarity = sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
    return max(-1.0, min(1.0, similarity))


def _pairwise_similarities(
    evidence_ids: list[str],
    embedding_records: Mapping[str, EvidenceEmbeddingRecord],
) -> dict[tuple[str, str], float]:
    similarities: dict[tuple[str, str], float] = {}
    for left_index, left_id in enumerate(evidence_ids):
        for right_id in evidence_ids[left_index + 1 :]:
            similarities[(left_id, right_id)] = cosine_similarity(
                embedding_records[left_id].embedding,
                embedding_records[right_id].embedding,
            )
    return similarities


def _neighbor_ranks(
    evidence_ids: list[str],
    similarities: dict[tuple[str, str], float],
) -> dict[str, dict[str, int]]:
    ranks: dict[str, dict[str, int]] = {}
    for evidence_id in evidence_ids:
        neighbors = sorted(
            (
                (
                    other_id,
                    similarities[
                        tuple(sorted((evidence_id, other_id)))
                    ],
                )
                for other_id in evidence_ids
                if other_id != evidence_id
            ),
            key=lambda item: (-item[1], item[0]),
        )
        ranks[evidence_id] = {
            other_id: rank
            for rank, (other_id, _similarity) in enumerate(neighbors, start=1)
        }
    return ranks


def _pair_id(left_evidence_id: str, right_evidence_id: str) -> str:
    digest = sha256(
        f"{left_evidence_id}\0{right_evidence_id}".encode()
    ).hexdigest()
    return f"pair-{digest}"
