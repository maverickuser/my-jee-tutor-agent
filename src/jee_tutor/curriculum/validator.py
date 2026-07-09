from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from jee_tutor.curriculum.taxonomy import CurriculumTaxonomy


UNABLE_TO_DETERMINE_SENTINEL = "Unable to determine from image"


@dataclass(frozen=True)
class CurriculumValidationResult:
    valid: bool
    category: str | None = None
    message: str | None = None
    taxonomy_version: str | None = None
    low_confidence_count: int = 0


class CurriculumValidationError(ValueError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class _TopicPath:
    subject: str
    chapter: str
    topic: str


class CurriculumValidator:
    def __init__(self, taxonomy: CurriculumTaxonomy | None = None, *, loader: Any = None):
        self.taxonomy = taxonomy
        self.loader = loader

    def validate(self, diagnosis: Any) -> CurriculumValidationResult:
        taxonomy = self.taxonomy
        if taxonomy is None and self.loader is not None:
            taxonomy = self.loader.load()
        if taxonomy is None:
            return CurriculumValidationResult(valid=True)
        return validate_diagnosis_against_taxonomy(diagnosis, taxonomy)


def validate_diagnosis_against_taxonomy(
    diagnosis: Any,
    taxonomy: CurriculumTaxonomy,
) -> CurriculumValidationResult:
    low_confidence_count = 0
    for question in diagnosis.questions:
        chapter = question.chapter
        topic = question.topic
        chapter_unknown = _is_unable_to_determine(chapter)
        topic_unknown = _is_unable_to_determine(topic)
        if chapter_unknown and topic_unknown:
            low_confidence_count += 1
            continue
        if chapter_unknown or topic_unknown:
            return _failure("partial_curriculum_label", taxonomy)

        chapter_matches = _chapter_matches(taxonomy, chapter)
        if not chapter_matches:
            return _failure("unknown_chapter", taxonomy)

        topic_paths = [
            path
            for path in chapter_matches
            if _label_matches_topic(
                taxonomy.subjects[path.subject].chapters[path.chapter].topics[path.topic],
                path.topic,
                topic,
            )
        ]
        if len(topic_paths) == 1:
            continue
        if len(topic_paths) > 1:
            return _failure("ambiguous_chapter_topic", taxonomy)

        if _topic_exists_anywhere(taxonomy, topic):
            return _failure("topic_not_in_chapter", taxonomy)
        return _failure("unknown_topic", taxonomy)

    return CurriculumValidationResult(
        valid=True,
        taxonomy_version=taxonomy.version,
        low_confidence_count=low_confidence_count,
    )


def normalize_label(value: str) -> str:
    normalized = value.strip().casefold().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _is_unable_to_determine(value: str) -> bool:
    return value.strip().casefold() == UNABLE_TO_DETERMINE_SENTINEL.casefold()


def _chapter_matches(taxonomy: CurriculumTaxonomy, chapter_label: str) -> list[_TopicPath]:
    label = normalize_label(chapter_label)
    paths: list[_TopicPath] = []
    for subject_name, subject in taxonomy.subjects.items():
        for chapter_name, chapter in subject.chapters.items():
            chapter_labels = [chapter_name, *chapter.aliases]
            if label not in {normalize_label(candidate) for candidate in chapter_labels}:
                continue
            for topic_name in chapter.topics:
                paths.append(_TopicPath(subject_name, chapter_name, topic_name))
    return paths


def _label_matches_topic(topic_model: Any, topic_name: str, topic_label: str) -> bool:
    label = normalize_label(topic_label)
    return label in {normalize_label(candidate) for candidate in [topic_name, *topic_model.aliases]}


def _topic_exists_anywhere(taxonomy: CurriculumTaxonomy, topic_label: str) -> bool:
    label = normalize_label(topic_label)
    for subject in taxonomy.subjects.values():
        for chapter in subject.chapters.values():
            for topic_name, topic in chapter.topics.items():
                if label in {normalize_label(candidate) for candidate in [topic_name, *topic.aliases]}:
                    return True
    return False


def _failure(category: str, taxonomy: CurriculumTaxonomy) -> CurriculumValidationResult:
    return CurriculumValidationResult(
        valid=False,
        category=category,
        message=f"Curriculum taxonomy validation failed: {category}.",
        taxonomy_version=taxonomy.version,
    )
