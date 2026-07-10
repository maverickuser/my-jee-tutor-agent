from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from jee_tutor.curriculum.taxonomy import CurriculumTaxonomy


UNABLE_TO_DETERMINE_SENTINEL = "Unable to determine from image"
TOPIC_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
    "without",
}


@dataclass(frozen=True)
class CurriculumValidationResult:
    valid: bool
    category: str | None = None
    message: str | None = None
    taxonomy_version: str | None = None
    low_confidence_count: int = 0
    details: dict[str, str | int | None] | None = None


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
            return _failure("partial_curriculum_label", taxonomy, question=question)

        chapter_matches = _chapter_matches(taxonomy, chapter)
        if not chapter_matches:
            return _failure("unknown_chapter", taxonomy, question=question)

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
            return _failure("ambiguous_chapter_topic", taxonomy, question=question)

        composite_matches = _chapter_topic_tokens_cover_label(taxonomy, chapter_matches, topic)
        if len(composite_matches) == 1:
            continue
        if len(composite_matches) > 1:
            return _failure("ambiguous_chapter_topic", taxonomy, question=question)

        if _topic_exists_anywhere(taxonomy, topic):
            return _failure("topic_not_in_chapter", taxonomy, question=question)
        return _failure("unknown_topic", taxonomy, question=question)

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


def _chapter_topic_tokens_cover_label(
    taxonomy: CurriculumTaxonomy,
    chapter_matches: list[_TopicPath],
    topic_label: str,
) -> set[tuple[str, str]]:
    requested_tokens = _significant_topic_tokens(topic_label)
    if len(requested_tokens) < 2:
        return set()

    matches: set[tuple[str, str]] = set()
    for subject_name, chapter_name in {(path.subject, path.chapter) for path in chapter_matches}:
        chapter = taxonomy.subjects[subject_name].chapters[chapter_name]
        chapter_tokens: set[str] = set()
        for topic_name, topic in chapter.topics.items():
            chapter_tokens.update(_significant_topic_tokens(topic_name))
            for alias in topic.aliases:
                chapter_tokens.update(_significant_topic_tokens(alias))
        if requested_tokens.issubset(chapter_tokens):
            matches.add((subject_name, chapter_name))
    return matches


def _significant_topic_tokens(label: str) -> set[str]:
    tokens = normalize_label(label).split()
    return {
        _topic_token_root(token)
        for token in tokens
        if token and token not in TOPIC_TOKEN_STOPWORDS and not token.isdigit()
    }


def _topic_token_root(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _failure(
    category: str,
    taxonomy: CurriculumTaxonomy,
    *,
    question: Any | None = None,
) -> CurriculumValidationResult:
    return CurriculumValidationResult(
        valid=False,
        category=category,
        message=f"Curriculum taxonomy validation failed: {category}.",
        taxonomy_version=taxonomy.version,
        details=_failure_details(question, taxonomy),
    )


def _failure_details(question: Any | None, taxonomy: CurriculumTaxonomy) -> dict[str, str | int | None] | None:
    if question is None:
        return None
    question_number = getattr(question, "question_number", None)
    chapter = str(getattr(question, "chapter", "") or "")
    topic = str(getattr(question, "topic", "") or "")
    return {
        "question_number": question_number,
        "chapter": _safe_log_label(chapter),
        "topic": _safe_log_label(topic),
        "normalized_chapter": normalize_label(chapter),
        "normalized_topic": normalize_label(topic),
        "taxonomy_version": taxonomy.version,
    }


def _safe_log_label(value: str, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", value.strip())[:limit]
