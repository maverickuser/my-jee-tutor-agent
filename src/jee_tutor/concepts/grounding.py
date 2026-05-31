from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from jee_tutor.concepts.graph import (
    ConceptGraphMatch,
    ConceptGraphRetriever,
    DynamoDBConceptGraphRetriever,
)


logger = logging.getLogger(__name__)

TABLE_COLUMNS = [
    "Question Number",
    "Chapter",
    "Topic",
    "What You Thought",
    "Why That Thought Is Wrong",
    "Exact Concept Gap",
    "What You Must Deep-Dive",
]


@dataclass
class GraphGroundingResult:
    analysis: str
    validation: dict[str, Any]


@dataclass
class MarkdownTable:
    rows: list[dict[str, str]]
    start_line: int
    end_line: int


class ConceptGraphGrounder:
    def __init__(
        self,
        retriever: ConceptGraphRetriever | None = None,
        *,
        max_depth: int | None = None,
    ):
        self.retriever = retriever or DynamoDBConceptGraphRetriever()
        self.max_depth = max_depth

    def ground(self, analysis: str, *, subject: str | None = None) -> GraphGroundingResult:
        try:
            table = _extract_markdown_table(analysis)
            if not table:
                match = self.retriever.validate(
                    subject=subject,
                    concept_gap=analysis[:500],
                    max_depth=self.max_depth,
                )
                return GraphGroundingResult(
                    analysis=analysis,
                    validation={"rows": [], "fallback": match.model_dump()},
                )

            grounded_rows = []
            validations = []
            for row in table.rows:
                graph_query_text = _graph_query_text(row)
                match = self.retriever.validate(
                    subject=subject,
                    chapter=row.get("Chapter"),
                    topic=row.get("Topic"),
                    microconcept=row.get("Exact Concept Gap"),
                    concept_gap=graph_query_text,
                    max_depth=self.max_depth,
                )
                validations.append(
                    {
                        "question_number": row.get("Question Number"),
                        **match.model_dump(),
                    }
                )
                grounded_rows.append(_ground_row(row, match))

            return GraphGroundingResult(
                analysis=_replace_table(analysis, table, grounded_rows),
                validation={"rows": validations},
            )
        except Exception as exc:
            logger.exception(
                "concept_graph_grounding_failed error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )
            return GraphGroundingResult(
                analysis=analysis,
                validation={
                    "error": f"{exc.__class__.__name__}: {exc or '[no message]'}",
                    "degraded_to_baseline": True,
                },
            )


def _ground_row(row: dict[str, str], match: ConceptGraphMatch) -> dict[str, str]:
    if not match.matched or match.confidence not in {"high", "medium"}:
        return dict(row)

    grounded = dict(row)
    grounded["Chapter"] = match.canonical_chapter or grounded.get("Chapter", "")
    grounded["Topic"] = match.canonical_topic or grounded.get("Topic", "")
    grounded["Exact Concept Gap"] = (
        match.canonical_microconcept or grounded.get("Exact Concept Gap", "")
    )
    if match.deep_dive:
        grounded["What You Must Deep-Dive"] = "; ".join(match.deep_dive)
    return grounded


def _graph_query_text(row: dict[str, str]) -> str:
    return " ".join(
        value
        for value in (
            row.get("Exact Concept Gap"),
            row.get("What You Must Deep-Dive"),
            row.get("Why That Thought Is Wrong"),
        )
        if value
    )


def _extract_markdown_table(text: str) -> MarkdownTable | None:
    lines = text.splitlines()
    parsed_rows = [
        (index, row)
        for index, line in enumerate(lines)
        if (row := _split_markdown_table_row(line))
    ]
    for parsed_index, (line_index, row) in enumerate(parsed_rows):
        if not _is_separator_row(row) or parsed_index == 0:
            continue
        headers = parsed_rows[parsed_index - 1][1]
        if not {"Chapter", "Topic", "Exact Concept Gap"}.issubset(set(headers)):
            continue
        data_rows = []
        end_line = line_index
        for data_line_index, candidate in parsed_rows[parsed_index + 1 :]:
            if data_line_index != end_line + 1:
                break
            if _is_separator_row(candidate):
                continue
            data_rows.append(candidate)
            end_line = data_line_index
        return MarkdownTable(
            rows=[dict(zip(headers, values, strict=False)) for values in data_rows],
            start_line=parsed_rows[parsed_index - 1][0],
            end_line=end_line,
        )
    return None


def _replace_table(text: str, table: MarkdownTable, rows: list[dict[str, str]]) -> str:
    lines = text.splitlines()
    replacement = _render_markdown_table(rows).splitlines()
    return "\n".join(lines[: table.start_line] + replacement + lines[table.end_line + 1 :])


def _render_markdown_table(rows: list[dict[str, str]]) -> str:
    lines = [
        "| " + " | ".join(TABLE_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in TABLE_COLUMNS) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_clean_cell(row.get(column, "")) for column in TABLE_COLUMNS) + " |")
    return "\n".join(lines)


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [_clean_cell(cell) for cell in stripped.strip("|").split("|")]


def _is_separator_row(row: list[str]) -> bool:
    return bool(row) and all(set(cell.replace(" ", "")) <= {"-", ":"} for cell in row)


def _clean_cell(value: str) -> str:
    return " ".join(str(value).replace("|", "/").split())
