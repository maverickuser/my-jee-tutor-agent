from collections import Counter
from dataclasses import dataclass
import re


REQUIRED_MARKDOWN_COLUMNS = [
    "Question Number",
    "Chapter",
    "Topic",
    "What You Thought",
    "Why That Thought Is Wrong",
    "Exact Concept Gap",
    "What You Must Deep-Dive",
]


class OutputValidationError(ValueError):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


@dataclass(frozen=True)
class MarkdownValidationResult:
    row_count: int
    question_numbers: list[str | None]


def validate_markdown_analysis(
    analysis: str,
    *,
    expected_image_count: int,
    expected_question_numbers: list[str | None],
) -> MarkdownValidationResult:
    table = _parse_markdown_table(analysis)
    missing_columns = [
        column
        for column in REQUIRED_MARKDOWN_COLUMNS
        if _normalize_column(column) not in table.normalized_headers
    ]
    if missing_columns:
        raise OutputValidationError(
            "Analysis markdown table is missing required columns.",
            [f"Missing columns: {', '.join(missing_columns)}."],
        )

    if len(table.rows) != expected_image_count:
        raise OutputValidationError(
            "Analysis row count does not match resolved image count.",
            [
                f"Resolved image count: {expected_image_count}.",
                f"Markdown data row count: {len(table.rows)}.",
            ],
        )

    question_index = table.normalized_headers.index(_normalize_column("Question Number"))
    actual_question_numbers = [
        _normalize_question_number(row[question_index] if question_index < len(row) else "")
        for row in table.rows
    ]
    _validate_question_numbers(expected_question_numbers, actual_question_numbers)

    return MarkdownValidationResult(
        row_count=len(table.rows),
        question_numbers=actual_question_numbers,
    )


@dataclass(frozen=True)
class _MarkdownTable:
    headers: list[str]
    rows: list[list[str]]

    @property
    def normalized_headers(self) -> list[str]:
        return [_normalize_column(header) for header in self.headers]


def _parse_markdown_table(analysis: str) -> _MarkdownTable:
    table_lines = [
        line.strip()
        for line in analysis.splitlines()
        if line.strip().startswith("|") and "|" in line.strip()[1:]
    ]
    if len(table_lines) < 3:
        raise OutputValidationError("Analysis output is not a markdown table.")

    headers = _split_markdown_row(table_lines[0])
    separator_index = 1
    if not _is_separator_row(table_lines[separator_index]):
        raise OutputValidationError("Analysis markdown table is missing a separator row.")

    rows = [
        cells
        for cells in (_split_markdown_row(line) for line in table_lines[separator_index + 1 :])
        if cells and not _is_separator_cells(cells)
    ]
    if not rows:
        raise OutputValidationError("Analysis markdown table has no data rows.")

    return _MarkdownTable(headers=headers, rows=rows)


def _split_markdown_row(line: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line.strip().strip("|"):
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            current.append(character)
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    cells.append("".join(current).strip())
    return cells


def _is_separator_row(line: str) -> bool:
    return _is_separator_cells(_split_markdown_row(line))


def _is_separator_cells(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _normalize_column(column: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", column.lower())


def _normalize_question_number(value: str) -> str | None:
    matches = re.findall(r"\d+", value)
    if not matches:
        return None
    return str(int(matches[-1]))


def _validate_question_numbers(
    expected_question_numbers: list[str | None],
    actual_question_numbers: list[str | None],
) -> None:
    if not expected_question_numbers or all(number is None for number in expected_question_numbers):
        return

    if any(number is None for number in expected_question_numbers):
        raise OutputValidationError(
            "Some image filenames do not contain question numbers.",
            [f"Expected question numbers: {_format_numbers(expected_question_numbers)}."],
        )
    if any(number is None for number in actual_question_numbers):
        raise OutputValidationError(
            "Some markdown rows do not contain question numbers.",
            [
                f"Expected question numbers: {_format_numbers(expected_question_numbers)}.",
                f"Actual question numbers: {_format_numbers(actual_question_numbers)}.",
            ],
        )

    expected_counts = Counter(expected_question_numbers)
    actual_counts = Counter(actual_question_numbers)
    if expected_counts != actual_counts:
        raise OutputValidationError(
            "Markdown question numbers do not match image filenames.",
            [
                f"Expected question numbers: {_format_numbers(expected_question_numbers)}.",
                f"Actual question numbers: {_format_numbers(actual_question_numbers)}.",
            ],
        )


def _format_numbers(question_numbers: list[str | None]) -> str:
    return ", ".join(number if number is not None else "[missing]" for number in question_numbers)
