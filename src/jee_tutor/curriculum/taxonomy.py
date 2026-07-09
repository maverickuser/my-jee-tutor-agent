from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = None
    uri: str
    etag: str | None = None


class CurriculumTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aliases: list[str] = Field(default_factory=list)


class CurriculumChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aliases: list[str] = Field(default_factory=list)
    topics: dict[str, CurriculumTopic] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_topics(self) -> "CurriculumChapter":
        if not self.topics:
            raise ValueError("Curriculum chapters must define at least one topic.")
        return self


class CurriculumSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapters: dict[str, CurriculumChapter] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_chapters(self) -> "CurriculumSubject":
        if not self.chapters:
            raise ValueError("Curriculum subjects must define at least one chapter.")
        return self


class CurriculumTaxonomy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    source_documents: list[SourceDocument] = Field(default_factory=list)
    generated_at: str | None = None
    approved_at: str | None = None
    subjects: dict[str, CurriculumSubject] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_subjects(self) -> "CurriculumTaxonomy":
        if not self.subjects:
            raise ValueError("Curriculum taxonomy must define at least one subject.")
        return self
