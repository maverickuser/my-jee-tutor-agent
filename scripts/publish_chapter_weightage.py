from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError


DEFAULT_BUCKET = "jee-tutor-agent-terraform-state"
DEFAULT_PREFIX = "curriculum/chapter-weightage"
SUBJECT_FILES = ("chemistry.json", "maths.json", "physics.json")


def publish_chapter_weightage(
    *,
    source_dir: Path,
    bucket: str = DEFAULT_BUCKET,
    prefix: str = DEFAULT_PREFIX,
    s3_client: Any | None = None,
) -> list[dict[str, Any]]:
    s3 = s3_client or boto3.client("s3", region_name="ap-south-1")
    results: list[dict[str, Any]] = []
    for filename in SUBJECT_FILES:
        path = source_dir / filename
        body = path.read_bytes()
        document = json.loads(body)
        _validate_document(document, filename)
        sha256 = hashlib.sha256(body).hexdigest()
        key = f"{prefix.strip('/')}/{filename}"
        remote_sha256 = _remote_sha256(s3, bucket, key)
        if remote_sha256 == sha256:
            results.append(
                {
                    "subject": document["subject"],
                    "uploaded": False,
                    "reason": "unchanged",
                    "s3_uri": f"s3://{bucket}/{key}",
                    "sha256": sha256,
                }
            )
            continue
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            Metadata={
                "schema-version": document["schema_version"],
                "sha256": sha256,
                "subject": document["subject"],
            },
        )
        results.append(
            {
                "subject": document["subject"],
                "uploaded": True,
                "reason": "missing" if remote_sha256 is None else "changed",
                "s3_uri": f"s3://{bucket}/{key}",
                "sha256": sha256,
            }
        )
    return results


def _validate_document(document: object, filename: str) -> None:
    if not isinstance(document, dict):
        raise ValueError(f"{filename} must contain a JSON object.")
    if document.get("schema_version") != "1.0":
        raise ValueError(f"{filename} has an unsupported schema_version.")
    if not isinstance(document.get("subject"), str) or not document["subject"].strip():
        raise ValueError(f"{filename} must contain a non-blank subject.")
    chapters = document.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError(f"{filename} must contain a non-empty chapters list.")
    expected_rank = 1
    previous_weight = float("inf")
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise ValueError(f"{filename} contains an invalid chapter record.")
        if chapter.get("rank") != expected_rank:
            raise ValueError(f"{filename} chapter ranks must be contiguous from 1.")
        weight = chapter.get("combined_weightage_percent")
        if not isinstance(weight, int | float) or weight < 0 or weight > previous_weight:
            raise ValueError(
                f"{filename} combined weights must be numeric and descending."
            )
        if not isinstance(chapter.get("chapter"), str) or not chapter["chapter"].strip():
            raise ValueError(f"{filename} contains a blank chapter name.")
        expected_rank += 1
        previous_weight = float(weight)


def _remote_sha256(s3: Any, bucket: str, key: str) -> str | None:
    try:
        response = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    return response.get("Metadata", {}).get("sha256")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish normalized JEE chapter-weightage JSON files."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("knowledge/chapter_weightage"),
    )
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    args = parser.parse_args()
    result = publish_chapter_weightage(
        source_dir=args.source_dir,
        bucket=args.bucket,
        prefix=args.prefix,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
