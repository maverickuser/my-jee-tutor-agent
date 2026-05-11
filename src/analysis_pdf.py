from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


PANDOC_MARKDOWN_FORMAT = "markdown+pipe_tables+tex_math_dollars+raw_tex"

PANDOC_LATEX_HEADER = r"""
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{array}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{makecell}
\usepackage[version=4]{mhchem}
\renewcommand{\arraystretch}{1.25}
"""

PANDOC_PDF_ARGS = [
    "--pdf-engine=xelatex",
    "--standalone",
    "-V",
    "geometry:landscape",
    "-V",
    "geometry:margin=1cm",
]

PandocConvertFunction = Callable[..., Any]


class PandocPdfRenderer:
    def __init__(self, *, converter: PandocConvertFunction | None = None):
        self.converter = converter or self._convert_with_pypandoc

    def render(self, markdown: str) -> bytes:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            header_path = temp_path / "latex-header.tex"
            output_path = temp_path / "analysis.pdf"
            header_path.write_text(PANDOC_LATEX_HEADER, encoding="utf-8")

            self.converter(
                markdown,
                "pdf",
                format=PANDOC_MARKDOWN_FORMAT,
                outputfile=str(output_path),
                extra_args=[*PANDOC_PDF_ARGS, f"--include-in-header={header_path}"],
            )
            return output_path.read_bytes()

    @staticmethod
    def _convert_with_pypandoc(*args: Any, **kwargs: Any) -> Any:
        import pypandoc

        return pypandoc.convert_text(*args, **kwargs)
