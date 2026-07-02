from __future__ import annotations

import argparse
import json
import time
import uuid
from urllib.parse import urlparse

import boto3

from eval_runner import write_report


def invoke_runtime(client, runtime_arn: str, payload: dict) -> dict:
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        qualifier="DEFAULT",
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(payload).encode(),
    )
    body = response["response"].read()
    return json.loads(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--image-s3-prefix", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", default="eval_runs/agentcore-smoke.json")
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    payload = {
        "task": "Run the deployed quality-pipeline smoke evaluation.",
        "subject": f"cd-smoke-{run_id}",
        "image_s3_prefix": args.image_s3_prefix,
        "idempotency_key": f"cd-smoke-{run_id}",
        "save_analysis_pdf": True,
    }
    started = time.time()
    client = boto3.client("bedrock-agentcore")
    failures = []
    try:
        first = invoke_runtime(client, args.runtime_arn, payload)
        second = invoke_runtime(client, args.runtime_arn, payload)
        if "error" in first:
            failures.append("runtime_returned_error")
        if first != second:
            failures.append("idempotent_response_mismatch")
        if first.get("runtime_commit_sha") != args.expected_sha:
            failures.append("deployed_sha_mismatch")
        pdf_uri = first.get("analysis_pdf_uri")
        if not pdf_uri:
            failures.append("pdf_uri_missing")
        else:
            parsed = urlparse(pdf_uri)
            head = boto3.client("s3").head_object(
                Bucket=parsed.netloc,
                Key=parsed.path.lstrip("/"),
            )
            if head["LastModified"].timestamp() < started:
                failures.append("pdf_predates_smoke_run")
        report = {
            "gate_passed": not failures,
            "run_id": run_id,
            "runtime_arn": args.runtime_arn,
            "expected_sha": args.expected_sha,
            "actual_sha": first.get("runtime_commit_sha"),
            "artifact_created": bool(pdf_uri),
            "idempotency_replayed": first == second,
            "failed_assertions": failures,
        }
    except Exception as exc:
        report = {
            "gate_passed": False,
            "run_id": run_id,
            "error_type": type(exc).__name__,
            "reason": (str(exc) or "[no message]")[:500],
        }
    write_report(report, args.output)
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
