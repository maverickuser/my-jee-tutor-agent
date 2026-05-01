import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import unquote_plus

import boto3

from agents.tutor_agent import run_tutor_workflow


LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

s3_client = boto3.client("s3")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET")
OUTPUT_PREFIX = os.getenv("OUTPUT_PREFIX", "outputs/")


def _make_data_uri(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    mime_type = "image/png" if suffix == ".png" else "image/jpeg"

    encoded = base64.b64encode(file_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _build_output_key(input_key: str) -> str:
    file_stem = Path(input_key).stem
    return f"{OUTPUT_PREFIX}{file_stem}.json"


def lambda_handler(event, context):
    LOGGER.info("Received S3 event: %s", json.dumps(event))

    record = event["Records"][0]
    source_bucket = record["s3"]["bucket"]["name"]
    object_key = unquote_plus(record["s3"]["object"]["key"])

    if not object_key.startswith("uploads/"):
        raise ValueError(f"Unexpected object key outside uploads/ prefix: {object_key}")

    with tempfile.TemporaryDirectory() as temp_dir:
        local_path = Path(temp_dir) / Path(object_key).name
        s3_client.download_file(source_bucket, object_key, str(local_path))

        question_context = (
            record.get("s3", {})
            .get("object", {})
            .get("metadata", {})
        )
        image_data_uri = _make_data_uri(local_path)
        analysis = run_tutor_workflow(
            image_data_uri=image_data_uri,
            question_context=json.dumps(question_context) if question_context else None,
        )

    output_key = _build_output_key(object_key)
    destination_bucket = OUTPUT_BUCKET or source_bucket
    payload = {
        "source_bucket": source_bucket,
        "source_key": object_key,
        "destination_bucket": destination_bucket,
        "output_key": output_key,
        "analysis": analysis,
        "request_id": getattr(context, "aws_request_id", None),
    }

    s3_client.put_object(
        Bucket=destination_bucket,
        Key=output_key,
        Body=json.dumps(payload, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "Analysis completed successfully.",
                "output_key": output_key,
            }
        ),
    }
