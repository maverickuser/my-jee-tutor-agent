from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3

from jee_tutor.curriculum.taxonomy import CurriculumTaxonomy


TaxonomyExtractor = Callable[[list[dict[str, Any]], str], dict[str, Any]]


@dataclass(frozen=True)
class BuildCurriculumTaxonomyConfig:
    source_pdf_s3_uris: list[str]
    output_s3_uri: str
    taxonomy_version: str
    publish_taxonomy: bool = False
    artifact_path: str = "eval_runs/jee_curriculum_taxonomy.json"

    @classmethod
    def from_environment(
        cls,
        environ: dict[str, str] | None = None,
    ) -> "BuildCurriculumTaxonomyConfig":
        env = environ if environ is not None else os.environ
        return cls(
            source_pdf_s3_uris=[
                value.strip()
                for value in env.get("CURRICULUM_SOURCE_PDF_S3_URIS", "").split(",")
                if value.strip()
            ],
            output_s3_uri=env.get("CURRICULUM_TAXONOMY_OUTPUT_S3_URI", "").strip(),
            taxonomy_version=env.get("CURRICULUM_TAXONOMY_VERSION", "").strip(),
            publish_taxonomy=_bool(env.get("PUBLISH_TAXONOMY", "false")),
            artifact_path=env.get(
                "CURRICULUM_TAXONOMY_ARTIFACT_PATH",
                "eval_runs/jee_curriculum_taxonomy.json",
            ),
        )


def build_curriculum_taxonomy(
    config: BuildCurriculumTaxonomyConfig,
    *,
    s3_client: Any | None = None,
    extractor: TaxonomyExtractor | None = None,
) -> CurriculumTaxonomy:
    _validate_config(config)
    s3 = s3_client or boto3.client("s3")
    source_documents = [_download_source_pdf(s3, uri) for uri in config.source_pdf_s3_uris]
    draft_payload = (extractor or _missing_extractor)(source_documents, config.taxonomy_version)
    draft_payload.setdefault("version", config.taxonomy_version)
    draft_payload.setdefault(
        "source_documents",
        [
            {
                "subject": document.get("subject"),
                "uri": document["uri"],
                "etag": document.get("etag"),
            }
            for document in source_documents
        ],
    )
    taxonomy = CurriculumTaxonomy.model_validate(draft_payload)
    _run_sanity_checks(taxonomy)
    _write_artifact(config.artifact_path, taxonomy)
    if config.publish_taxonomy:
        _publish_taxonomy(s3, config.output_s3_uri, taxonomy)
    return taxonomy


def _validate_config(config: BuildCurriculumTaxonomyConfig) -> None:
    if not config.source_pdf_s3_uris:
        raise ValueError("CURRICULUM_SOURCE_PDF_S3_URIS must include at least one S3 URI.")
    if not config.output_s3_uri:
        raise ValueError("CURRICULUM_TAXONOMY_OUTPUT_S3_URI must be set.")
    if not config.taxonomy_version:
        raise ValueError("CURRICULUM_TAXONOMY_VERSION must be set.")


def _download_source_pdf(s3: Any, uri: str) -> dict[str, Any]:
    bucket, key = _parse_s3_uri(uri)
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    if not body:
        raise ValueError(f"Source PDF is empty: {uri}")
    return {
        "uri": uri,
        "etag": str(response.get("ETag", "")).strip('"') or None,
        "bytes": body,
        "subject": _subject_from_key(key),
    }


def _missing_extractor(_source_documents: list[dict[str, Any]], _version: str) -> dict[str, Any]:
    raise RuntimeError("Curriculum taxonomy extraction hook is not configured.")


def _run_sanity_checks(taxonomy: CurriculumTaxonomy) -> None:
    for subject_name, subject in taxonomy.subjects.items():
        if not subject.chapters:
            raise ValueError(f"Subject has no chapters: {subject_name}")
        for chapter_name, chapter in subject.chapters.items():
            if not chapter.topics:
                raise ValueError(f"Chapter has no topics: {subject_name}/{chapter_name}")


def _write_artifact(path: str, taxonomy: CurriculumTaxonomy) -> None:
    artifact = Path(path)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        taxonomy.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _publish_taxonomy(s3: Any, output_s3_uri: str, taxonomy: CurriculumTaxonomy) -> None:
    bucket, key = _parse_s3_uri(output_s3_uri)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=taxonomy.model_dump_json(indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _subject_from_key(key: str) -> str | None:
    lower = key.lower()
    for subject in ["math", "maths", "mathematics", "physics", "chemistry"]:
        if subject in lower:
            return "Mathematics" if subject in {"math", "maths"} else subject.title()
    return None


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    build_curriculum_taxonomy(BuildCurriculumTaxonomyConfig.from_environment())


if __name__ == "__main__":
    main()
