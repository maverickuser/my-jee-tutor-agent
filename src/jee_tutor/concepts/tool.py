from __future__ import annotations

import json
import logging
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.concepts.graph import (
    ConceptGraphRetriever,
    DynamoDBConceptGraphRetriever,
)


logger = logging.getLogger(__name__)


class ConceptGraphInput(BaseModel):
    subject: str | None = Field(default=None, description="Subject, for example physics.")
    chapter: str | None = Field(default=None, description="Chapter proposed by the vision analysis.")
    topic: str | None = Field(default=None, description="Topic proposed by the vision analysis.")
    microconcept: str | None = Field(
        default=None,
        description="Specific microconcept proposed by the vision analysis.",
    )
    concept_gap: str | None = Field(
        default=None,
        description="Concept gap or prerequisite gap proposed by the vision analysis.",
    )
    max_depth: int = Field(default=2, ge=1, le=5)


class ConceptGraphTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "concept_graph_validate"
    description: str = (
        "Validate and normalize JEE concept labels against the concept graph. "
        "Use this after vision analysis identifies a chapter, topic, microconcept, "
        "or concept gap. Returns canonical labels, prerequisites, common confusions, "
        "and recommended deep-dive concepts."
    )
    args_schema: type[BaseModel] = ConceptGraphInput
    retriever: Any = Field(
        default_factory=DynamoDBConceptGraphRetriever,
        exclude=True,
    )

    def _run(
        self,
        subject: str | None = None,
        chapter: str | None = None,
        topic: str | None = None,
        microconcept: str | None = None,
        concept_gap: str | None = None,
        max_depth: int = 2,
    ) -> str:
        try:
            match = self.retriever.validate(
                subject=subject,
                chapter=chapter,
                topic=topic,
                microconcept=microconcept,
                concept_gap=concept_gap,
                max_depth=max_depth,
            )
            payload = match.model_dump()
        except Exception as exc:
            logger.exception(
                "concept_graph_tool_error error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )
            payload = {
                "matched": False,
                "confidence": "error",
                "error": f"{exc.__class__.__name__}: {exc or '[no message]'}",
            }
        return json.dumps(payload, sort_keys=True)


def build_concept_graph_tool(
    retriever: ConceptGraphRetriever | None = None,
) -> ConceptGraphTool:
    return ConceptGraphTool(retriever=retriever or DynamoDBConceptGraphRetriever())
