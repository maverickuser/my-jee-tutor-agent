from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

from jee_tutor.curriculum.taxonomy import CurriculumTaxonomy


def publish_curriculum_taxonomy(
    *,
    taxonomy_file: Path,
    s3_uri: str,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    body = taxonomy_file.read_bytes()
    taxonomy = CurriculumTaxonomy.model_validate_json(body)
    local_sha256 = hashlib.sha256(body).hexdigest()
    bucket, key = _parse_s3_uri(s3_uri)
    s3 = s3_client or boto3.client("s3")

    remote = _load_remote_taxonomy(s3, bucket, key)
    if remote and remote["version"] == taxonomy.version and remote["sha256"] == local_sha256:
        return {
            "uploaded": False,
            "reason": "unchanged",
            "s3_uri": s3_uri,
            "version": taxonomy.version,
            "sha256": local_sha256,
        }

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        Metadata={
            "taxonomy-version": taxonomy.version,
            "sha256": local_sha256,
        },
    )
    return {
        "uploaded": True,
        "reason": "missing" if remote is None else "changed",
        "s3_uri": s3_uri,
        "version": taxonomy.version,
        "sha256": local_sha256,
        "previous_version": remote["version"] if remote else None,
        "previous_sha256": remote["sha256"] if remote else None,
    }


def _load_remote_taxonomy(s3: Any, bucket: str, key: str) -> dict[str, str] | None:
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise

    body = response["Body"].read()
    taxonomy = CurriculumTaxonomy.model_validate_json(body)
    return {
        "version": taxonomy.version,
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish approved curriculum taxonomy JSON.")
    parser.add_argument(
        "--taxonomy-file",
        default="knowledge/jee_curriculum_taxonomy.json",
        type=Path,
    )
    parser.add_argument("--s3-uri", required=True)
    args = parser.parse_args()

    result = publish_curriculum_taxonomy(
        taxonomy_file=args.taxonomy_file,
        s3_uri=args.s3_uri,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
