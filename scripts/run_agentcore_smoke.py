from __future__ import annotations

import argparse
import json
import time
import uuid
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from eval_runner import write_report


AGENTCORE_READ_TIMEOUT_SECONDS = 900
IN_PROGRESS_ERROR = "Tutor invocation is already in progress."
IN_PROGRESS_POLL_INTERVAL_SECONDS = 5.0
IN_PROGRESS_POLL_TIMEOUT_SECONDS = 300.0
MAX_RUNTIME_ERROR_DETAILS = 20


def markdown_data_row_count(text: str) -> int:
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in text.splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    ]
    for index, row in enumerate(rows):
        if index == 0 or not _is_separator_row(row):
            continue
        return sum(not _is_separator_row(candidate) for candidate in rows[index + 1 :])
    return 0


def _is_separator_row(row: list[str]) -> bool:
    return bool(row) and all(set(cell.replace(" ", "")) <= {"-", ":"} for cell in row)


def invoke_runtime(
    client,
    runtime_arn: str,
    runtime_session_id: str,
    payload: dict,
) -> dict:
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=runtime_session_id,
        qualifier="DEFAULT",
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(payload).encode(),
    )
    body = response["response"].read()
    return json.loads(body)


def invoke_until_terminal(
    client,
    runtime_arn: str,
    runtime_session_id: str,
    payload: dict,
    *,
    poll_interval_seconds: float = IN_PROGRESS_POLL_INTERVAL_SECONDS,
    poll_timeout_seconds: float = IN_PROGRESS_POLL_TIMEOUT_SECONDS,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> tuple[dict, int]:
    started = monotonic()
    poll_count = 0
    while True:
        response = invoke_runtime(
            client,
            runtime_arn,
            runtime_session_id,
            payload,
        )
        if response.get("error") != IN_PROGRESS_ERROR:
            return response, poll_count

        remaining = poll_timeout_seconds - (monotonic() - started)
        if remaining <= 0:
            return response, poll_count

        poll_count += 1
        sleep(min(poll_interval_seconds, remaining))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--image-s3-prefix", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-image-count", required=True, type=int)
    parser.add_argument(
        "--save-analysis-pdf",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--output", default="eval_runs/agentcore-smoke.json")
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    payload = {
        "task": "Run the deployed quality-pipeline smoke evaluation.",
        "subject": f"cd-smoke-{run_id}",
        "image_s3_prefix": args.image_s3_prefix,
        "idempotency_key": f"cd-smoke-{run_id}",
        "save_analysis_pdf": args.save_analysis_pdf,
    }
    started = time.time()
    client = boto3.client(
        "bedrock-agentcore",
        config=Config(
            connect_timeout=10,
            read_timeout=AGENTCORE_READ_TIMEOUT_SECONDS,
            retries={"mode": "standard", "total_max_attempts": 1},
            tcp_keepalive=True,
        ),
    )
    failures = []
    try:
        first, first_poll_count = invoke_until_terminal(
            client,
            args.runtime_arn,
            run_id,
            payload,
        )
        runtime_failed = "error" in first
        if runtime_failed:
            failures.append("runtime_returned_error")
        if first.get("runtime_commit_sha") != args.expected_sha:
            failures.append("deployed_sha_mismatch")
        analysis_data_row_count = (
            None if runtime_failed else markdown_data_row_count(str(first.get("analysis", "")))
        )
        if not runtime_failed and analysis_data_row_count != args.expected_image_count:
            failures.append("analysis_row_count_mismatch")
        pdf_uri = first.get("analysis_pdf_uri")
        first_artifact_head = None
        replay_artifact_head = None
        if args.save_analysis_pdf and not runtime_failed:
            if not pdf_uri:
                failures.append("pdf_uri_missing")
            else:
                parsed = urlparse(pdf_uri)
                s3_client = boto3.client("s3")
                first_artifact_head = s3_client.head_object(
                    Bucket=parsed.netloc,
                    Key=parsed.path.lstrip("/"),
                )
                if first_artifact_head["LastModified"].timestamp() < started:
                    failures.append("pdf_predates_smoke_run")

        second, second_poll_count = invoke_until_terminal(
            client,
            args.runtime_arn,
            run_id,
            payload,
        )
        if not runtime_failed and first != second:
            failures.append("idempotent_response_mismatch")

        artifact_last_modified_unchanged = None
        artifact_etag_unchanged = None
        if first_artifact_head is not None:
            replay_artifact_head = s3_client.head_object(
                Bucket=parsed.netloc,
                Key=parsed.path.lstrip("/"),
            )
            artifact_last_modified_unchanged = (
                replay_artifact_head["LastModified"] == first_artifact_head["LastModified"]
            )
            artifact_etag_unchanged = replay_artifact_head["ETag"] == first_artifact_head["ETag"]
            if not (artifact_last_modified_unchanged and artifact_etag_unchanged):
                failures.append("artifact_rewritten_on_idempotent_replay")

        report = {
            "gate_passed": not failures,
            "run_id": run_id,
            "runtime_arn": args.runtime_arn,
            "expected_sha": args.expected_sha,
            "actual_sha": first.get("runtime_commit_sha"),
            "expected_image_count": args.expected_image_count,
            "analysis_data_row_count": analysis_data_row_count,
            "artifact_requested": args.save_analysis_pdf,
            "artifact_created": bool(pdf_uri),
            "artifact_last_modified_unchanged": artifact_last_modified_unchanged,
            "artifact_etag_unchanged": artifact_etag_unchanged,
            "idempotency_replayed": first == second,
            "in_progress_poll_count": first_poll_count + second_poll_count,
            "failed_assertions": failures,
            "runtime_error": first.get("error"),
            "runtime_error_details": first.get("details", [])[:MAX_RUNTIME_ERROR_DETAILS],
        }
    except Exception as exc:
        report = {
            "gate_passed": False,
            "run_id": run_id,
            "error_type": type(exc).__name__,
            "reason": (str(exc) or "[no message]")[:500],
        }
    write_report(report, args.output)
    print(f"agentcore_smoke_report={json.dumps(report, sort_keys=True)}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
