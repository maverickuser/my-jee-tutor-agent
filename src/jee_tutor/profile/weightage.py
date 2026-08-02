"""Chapter-weightage lookup and repeated-mistake prioritization."""

from __future__ import annotations

from collections import Counter
import json
import logging
import os
import re
from typing import Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.profile.actionable import ImportantChapter
from jee_tutor.profile.evidence import ProfileEvidenceItem


logger = logging.getLogger(__name__)
DEFAULT_WEIGHTAGE_BUCKET = "jee-tutor-agent-terraform-state"
DEFAULT_WEIGHTAGE_PREFIX = "curriculum/chapter-weightage"
MAX_CHAPTER_PRIORITIES = 5

_CHAPTER_ALIASES: dict[str, tuple[str, ...]] = {
    "sets relations functions": ("sets", "relations", "functions"),
    "integration definite indefinite": (
        "integration",
        "definite integration",
        "indefinite integration",
    ),
    "three dimensional geometry": ("3d geometry", "three dimensional geometry"),
}


class S3ObjectReader(Protocol):
    def get_object(self, *, Bucket: str, Key: str) -> dict: ...


class ChapterWeightage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapter: str = Field(min_length=1)
    combined_weightage_percent: float = Field(gt=0)


class SubjectWeightage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapters: list[ChapterWeightage] = Field(min_length=1)


class ChapterWeightageService:
    """Load validated curriculum weights once and rank repeated mistake chapters."""

    def __init__(
        self,
        *,
        s3_client: S3ObjectReader | None = None,
        bucket: str | None = None,
        prefix: str | None = None,
    ):
        self._s3_client = s3_client
        self.bucket = bucket or os.getenv(
            "CHAPTER_WEIGHTAGE_S3_BUCKET", DEFAULT_WEIGHTAGE_BUCKET
        )
        configured_prefix = prefix or os.getenv(
            "CHAPTER_WEIGHTAGE_S3_PREFIX", DEFAULT_WEIGHTAGE_PREFIX
        )
        self.prefix = configured_prefix.strip("/")
        self._cache: dict[str, SubjectWeightage] = {}

    def priorities(
        self, *, subject: str, evidence_items: list[ProfileEvidenceItem]
    ) -> list[ImportantChapter]:
        curriculum = self._load_or_none(subject)
        if curriculum is None:
            return []
        mistakes = Counter(_normal(item.chapter) for item in evidence_items)
        result: list[ImportantChapter] = []
        for chapter in curriculum.chapters:
            count = _matched_count(chapter.chapter, mistakes)
            if count < 2:
                continue
            result.append(
                ImportantChapter(
                    chapter=chapter.chapter,
                    mistake_count=count,
                    combined_weightage_percent=chapter.combined_weightage_percent,
                )
            )
        return sorted(
            result,
            key=lambda item: (-item.combined_weightage_percent, -item.mistake_count),
        )[:MAX_CHAPTER_PRIORITIES]

    def _load_or_none(self, subject: str) -> SubjectWeightage | None:
        try:
            return self._load(subject)
        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "chapter_weightage_load_failed subject=%s error_type=%s",
                subject,
                exc.__class__.__name__,
            )
            return None

    def _load(self, subject: str) -> SubjectWeightage:
        key = subject.casefold()
        if key not in self._cache:
            client = self._s3_client or boto3.client("s3")
            response = client.get_object(
                Bucket=self.bucket,
                Key=f"{self.prefix}/{key}.json",
            )
            document = json.loads(response["Body"].read())
            self._cache[key] = SubjectWeightage.model_validate(document)
        return self._cache[key]


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _matched_count(chapter: str, mistakes: Counter[str]) -> int:
    wanted = _normal(chapter)
    candidates = (wanted, *_CHAPTER_ALIASES.get(wanted, ()))
    return sum(
        count
        for label, count in mistakes.items()
        if any(
            candidate == label or candidate in label or label in candidate
            for candidate in candidates
        )
    )


__all__ = ["ChapterWeightageService"]
