from __future__ import annotations

import argparse
import json
import re
import uuid
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from eval_runner import write_report
from run_agentcore_smoke import (
    AGENTCORE_READ_TIMEOUT_SECONDS,
    invoke_until_terminal,
)


MAX_RUNTIME_ERROR_DETAILS = 20


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--metadata-table-name", required=True)
    parser.add_argument("--embedding-table-name", required=True)
    parser.add_argument("--diagnosis-smoke-report", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--email-domain", default="example.com")
    parser.add_argument("--output", default="eval_runs/agentcore-profile-smoke.json")
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    email = f"cd-profile-smoke-{run_id}@{args.email_domain}"

    client = boto3.client(
        "bedrock-agentcore",
        config=Config(
            connect_timeout=10,
            read_timeout=AGENTCORE_READ_TIMEOUT_SECONDS,
            retries={"mode": "standard", "total_max_attempts": 1},
            tcp_keepalive=True,
        ),
    )
    failures: list[str] = []
    first: dict = {}
    second: dict = {}
    first_poll_count = 0
    second_poll_count = 0
    embedding_count = 0
    diagnosis_json_uri = None
    profile_report_pdf_uri = None
    subject = None
    try:
        diagnosis_smoke_report = _load_json_file(args.diagnosis_smoke_report)
        diagnosis_json_uri = diagnosis_smoke_report.get("diagnosis_json_uri")
        if not diagnosis_json_uri:
            failures.append("diagnosis_json_uri_missing")
            raise ProfileSmokePreconditionError(
                "Diagnosis smoke did not produce a structured diagnosis JSON URI."
            )

        report = _load_s3_json(diagnosis_json_uri)
        subject = report["subject"]
        metadata_item = _metadata_item(
            email=email,
            diagnosis_json_uri=diagnosis_json_uri,
            report=report,
        )
        payload = {
            "task": "profile",
            "recipient_email": email,
            "subject": subject,
            "idempotency_key": f"cd-profile-smoke-{run_id}",
        }
        _put_metadata(args.metadata_table_name, metadata_item)

        first, first_poll_count = invoke_until_terminal(
            client,
            args.runtime_arn,
            run_id,
            payload,
        )
        if "error" in first:
            failures.append("profile_runtime_returned_error")
        if first.get("runtime_commit_sha") != args.expected_sha:
            failures.append("deployed_sha_mismatch")
        if first.get("profile_status") != "succeeded":
            failures.append("profile_status_not_succeeded")
        if not first.get("profile_markdown"):
            failures.append("profile_markdown_missing")
        if first.get("profile_artifact_status") != "succeeded":
            failures.append("profile_artifact_not_succeeded")
        profile_report_pdf_uri = first.get("profile_report_pdf_uri")
        if not profile_report_pdf_uri:
            failures.append("profile_report_pdf_uri_missing")
        else:
            expected_key = _expected_profile_pdf_key(report, subject)
            if urlparse(profile_report_pdf_uri).path.lstrip("/") != expected_key:
                failures.append("profile_pdf_key_invalid")
            try:
                _head_s3_uri(profile_report_pdf_uri)
            except Exception:
                failures.append("profile_pdf_not_found")
        if "image_s3_prefix" in first or "analysis" in first:
            failures.append("profile_response_looks_like_diagnosis")

        embedding_count = _embedding_count(
            args.embedding_table_name,
            diagnosis_json_uri=diagnosis_json_uri,
        )
        if embedding_count < len(report["questions"]):
            failures.append("profile_embeddings_missing")

        second, second_poll_count = invoke_until_terminal(
            client,
            args.runtime_arn,
            run_id,
            payload,
        )
        if "error" in second:
            failures.append("profile_replay_returned_error")
        if second.get("profile_status") != "succeeded":
            failures.append("profile_replay_status_not_succeeded")

        smoke_report = {
            "gate_passed": not failures,
            "run_id": run_id,
            "runtime_arn": args.runtime_arn,
            "expected_sha": args.expected_sha,
            "actual_sha": first.get("runtime_commit_sha"),
            "subject": subject,
            "recipient_email": email,
            "diagnosis_json_uri": diagnosis_json_uri,
            "diagnosis_smoke_report": args.diagnosis_smoke_report,
            "metadata_table_name": args.metadata_table_name,
            "embedding_table_name": args.embedding_table_name,
            "profile_status": first.get("profile_status"),
            "profile_markdown_present": bool(first.get("profile_markdown")),
            "profile_artifact_status": first.get("profile_artifact_status"),
            "profile_report_pdf_uri": profile_report_pdf_uri,
            "profile_artifact_errors": first.get("profile_artifact_errors", []),
            "embedding_record_count": embedding_count,
            "idempotency_replay_succeeded": second.get("profile_status") == "succeeded",
            "in_progress_poll_count": first_poll_count + second_poll_count,
            "failed_assertions": failures,
            "runtime_error": first.get("error"),
            "runtime_error_details": first.get("details", [])[:MAX_RUNTIME_ERROR_DETAILS],
        }
    except ProfileSmokePreconditionError as exc:
        smoke_report = {
            "gate_passed": False,
            "run_id": run_id,
            "diagnosis_smoke_report": args.diagnosis_smoke_report,
            "diagnosis_json_uri": diagnosis_json_uri,
            "subject": subject,
            "profile_report_pdf_uri": profile_report_pdf_uri,
            "recipient_email": email,
            "failed_assertions": failures,
            "error_type": type(exc).__name__,
            "reason": str(exc),
        }
    except Exception as exc:
        smoke_report = {
            "gate_passed": False,
            "run_id": run_id,
            "error_type": type(exc).__name__,
            "reason": (str(exc) or "[no message]")[:500],
        }

    write_report(smoke_report, args.output)
    print(f"agentcore_profile_smoke_report={json.dumps(smoke_report, sort_keys=True)}")
    return 0 if smoke_report["gate_passed"] else 1


class ProfileSmokePreconditionError(RuntimeError):
    pass


def _expected_profile_pdf_key(report: dict, subject: str) -> str:
    student_name = _safe_path_part(str(report["student_name"]))
    student_id = _safe_path_part(str(report["student_id"]))
    safe_subject = _safe_path_part(subject)
    return (
        f"profile-reports/{student_name}+{student_id}/{safe_subject}/"
        f"{safe_subject}_profile_report.pdf"
    )


def _safe_path_part(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    if not normalized:
        raise ProfileSmokePreconditionError("Profile path component is blank.")
    return normalized


def _load_json_file(path: str) -> dict:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def _load_s3_json(s3_uri: str) -> dict:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    response = boto3.client("s3").get_object(
        Bucket=parsed.netloc,
        Key=parsed.path.lstrip("/"),
    )
    return json.loads(response["Body"].read().decode("utf-8"))


def _head_s3_uri(s3_uri: str) -> None:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    boto3.client("s3").head_object(
        Bucket=parsed.netloc,
        Key=parsed.path.lstrip("/"),
    )


def _metadata_item(*, email: str, diagnosis_json_uri: str, report: dict) -> dict:
    subject = report["subject"]
    diagnosis_date = report["diagnosis_date"]
    return {
        "email": email,
        "subject_report_key": f"{subject.casefold()}#{diagnosis_date}#{report['diagnosis_report_id']}",
        "student_id": report["student_id"],
        "student_name": report["student_name"],
        "subject": subject,
        "test_name": report["test_name"],
        "diagnosis_report_id": report["diagnosis_report_id"],
        "diagnosis_date": diagnosis_date,
        "diagnosis_json_s3_uri": diagnosis_json_uri,
        "question_count": len(report["questions"]),
    }


def _put_metadata(table_name: str, item: dict) -> None:
    boto3.resource("dynamodb").Table(table_name).put_item(Item=item)


def _embedding_count(table_name: str, *, diagnosis_json_uri: str) -> int:
    response = boto3.resource("dynamodb").Table(table_name).query(
        KeyConditionExpression="diagnosis_json_s3_uri = :diagnosis_json_uri",
        ExpressionAttributeValues={":diagnosis_json_uri": diagnosis_json_uri},
        Select="COUNT",
    )
    return int(response.get("Count", 0))


if __name__ == "__main__":
    raise SystemExit(main())
