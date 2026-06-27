import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

TUTOR_WORKFLOW_FAILURE_ERROR = "Tutor workflow failed while analyzing images."


class RetryableEvalError(RuntimeError):
    """Raised when an eval case hit transient provider/runtime infrastructure."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CD evals for the JEE tutor agent.")
    parser.add_argument("--cases", default="evals/jee_tutor_eval_cases.json")
    parser.add_argument(
        "--image-folder",
        default="tests/fixtures/image_folder",
        help="Local fixture folder used to build a single image_data_uri for non-S3 evals.",
    )
    parser.add_argument(
        "--image-s3-prefix",
        default=None,
        help="S3 prefix containing live eval attempt images. Overrides --image-folder.",
    )
    parser.add_argument("--output", default="eval_runs/agent-evals.json")
    parser.add_argument("--min-score", type=float, default=0.75)
    parser.add_argument("--case-attempts", type=int, default=3)
    parser.add_argument("--case-backoff-seconds", type=float, default=10.0)
    args = parser.parse_args()

    cases = _load_json(Path(args.cases))
    image_input = _image_input_payload(
        image_folder=args.image_folder,
        image_s3_prefix=args.image_s3_prefix,
    )
    results = [
        _run_case_with_retries(
            case,
            image_input,
            max_attempts=args.case_attempts,
            backoff_seconds=args.case_backoff_seconds,
        )
        for case in cases
    ]
    scored_results = [result for result in results if not result.get("skipped")]
    passed = sum(1 for result in scored_results if result["passed"])
    skipped = len(results) - len(scored_results)
    score = passed / len(scored_results) if scored_results else 0.0

    report = {
        "score": score,
        "passed": passed,
        "total": len(results),
        "scored_total": len(scored_results),
        "skipped": skipped,
        "min_score": args.min_score,
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _publish_langfuse_summary(report)

    print(
        f"agent_eval_score={score:.2f} "
        f"({passed}/{len(scored_results)} scored cases passed, {skipped} skipped)"
    )
    _print_failed_case_summary(results)
    _enforce_eval_gate(score=score, min_score=args.min_score, skipped=skipped)


def _load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_case_with_retries(
    case: dict[str, Any],
    image_input: dict[str, str],
    *,
    max_attempts: int,
    backoff_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    for attempt in range(1, max_attempts + 1):
        try:
            return _run_case(case, image_input)
        except Exception as exc:
            if attempt < max_attempts and _is_retryable_eval_error(exc):
                wait_seconds = backoff_seconds * attempt
                print(
                    f"eval_case_retry id={case['id']} attempt={attempt} "
                    f"wait_seconds={wait_seconds:.1f} error={_truncate(str(exc), 240)}"
                )
                sleep(wait_seconds)
                continue
            return _failed_case_result(case, exc, attempt)

    raise RuntimeError("Eval retry loop exhausted without returning.")


def _run_case(case: dict[str, Any], image_input: dict[str, str] | str) -> dict[str, Any]:
    from jee_tutor.handler import handle_tutor_invocation

    payload = {
        **_normalized_image_input(image_input),
        "task": case["task"],
        "save_analysis_pdf": False,
    }
    response = handle_tutor_invocation(payload)
    retryable_response_error = _retryable_response_error_reason(response)
    if retryable_response_error:
        raise RetryableEvalError(retryable_response_error)

    if case["type"] == "analysis":
        return _score_analysis_case(case, response)
    if case["type"] == "markdown_table":
        return _score_markdown_table_case(case, response)
    if case["type"] == "guardrail":
        return _score_guardrail_case(case, response)

    return {
        "id": case["id"],
        "type": case["type"],
        "passed": False,
        "reason": f"Unsupported eval case type: {case['type']}",
        "response": _redacted_response(response),
    }


def _image_input_payload(
    *,
    image_folder: str,
    image_s3_prefix: str | None,
) -> dict[str, str]:
    if image_s3_prefix:
        return {"image_s3_prefix": image_s3_prefix}
    return {"image_data_uri": _first_folder_image_data_uri(Path(image_folder).resolve())}


def _normalized_image_input(image_input: dict[str, str] | str) -> dict[str, str]:
    if isinstance(image_input, str):
        return {"image_data_uri": image_input}
    return image_input


def _first_folder_image_data_uri(image_folder: Path) -> str:
    supported_formats = {
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".png": "png",
        ".webp": "webp",
    }
    image_paths = sorted(
        path
        for path in image_folder.iterdir()
        if path.is_file() and path.suffix.lower() in supported_formats
    )
    if not image_paths:
        supported = ", ".join(sorted(supported_formats))
        raise ValueError(f"Image folder contains no supported images ({supported}): {image_folder}")

    image_path = image_paths[0]
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    image_format = supported_formats[image_path.suffix.lower()]
    return f"data:image/{image_format};base64,{encoded}"


def _score_analysis_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    analysis = response.get("analysis", "")
    normalized_analysis = analysis.lower()
    matched_terms = [
        term for term in case.get("required_terms", []) if term.lower() in normalized_analysis
    ]
    min_required_terms = int(case.get("min_required_terms", len(case.get("required_terms", []))))
    passed = bool(analysis.strip()) and len(matched_terms) >= min_required_terms

    return {
        "id": case["id"],
        "type": case["type"],
        "passed": passed,
        "matched_terms": matched_terms,
        "required_terms": case.get("required_terms", []),
        "min_required_terms": min_required_terms,
        "reason": None
        if passed
        else "Analysis was empty or did not include enough expected coaching structure terms.",
        "response": _redacted_response(response),
    }


def _score_markdown_table_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    analysis = str(response.get("analysis", ""))
    header_columns, data_rows = _extract_markdown_table(analysis)
    required_columns = case.get("required_columns", [])
    matched_columns = [
        column
        for column in required_columns
        if _normalize_table_cell(column)
        in {_normalize_table_cell(value) for value in header_columns}
    ]
    min_required_columns = int(case.get("min_required_columns", len(required_columns)))
    min_data_rows = int(case.get("min_data_rows", 1))
    passed = len(matched_columns) >= min_required_columns and len(data_rows) >= min_data_rows

    return {
        "id": case["id"],
        "type": case["type"],
        "passed": passed,
        "matched_columns": matched_columns,
        "required_columns": required_columns,
        "header_columns": header_columns,
        "data_row_count": len(data_rows),
        "min_required_columns": min_required_columns,
        "min_data_rows": min_data_rows,
        "reason": None
        if passed
        else "Analysis did not include the required markdown table structure.",
        "response": _redacted_response(response),
    }


def _extract_markdown_table(text: str) -> tuple[list[str], list[list[str]]]:
    rows = [_split_markdown_table_row(line) for line in text.splitlines()]
    rows = [row for row in rows if row]
    for index, row in enumerate(rows):
        if not _is_separator_row(row):
            continue
        if index == 0:
            continue
        header = rows[index - 1]
        data_rows = [
            candidate for candidate in rows[index + 1 :] if not _is_separator_row(candidate)
        ]
        return header, data_rows
    return [], []


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _is_separator_row(row: list[str]) -> bool:
    return bool(row) and all(set(cell.replace(" ", "")) <= {"-", ":"} for cell in row)


def _normalize_table_cell(value: str) -> str:
    return " ".join(value.casefold().split())


def _score_guardrail_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(
        [
            str(response.get("error", "")),
            str(response.get("analysis", "")),
            " ".join(str(detail) for detail in response.get("details", [])),
        ]
    ).lower()
    matched_markers = [
        marker for marker in case.get("expected_markers", []) if marker.lower() in text
    ]
    passed = "error" in response and bool(matched_markers)

    return {
        "id": case["id"],
        "type": case["type"],
        "passed": passed,
        "matched_markers": matched_markers,
        "expected_markers": case.get("expected_markers", []),
        "reason": None if passed else "Guardrail did not return the expected block response.",
        "response": _redacted_response(response),
    }


def _failed_case_result(case: dict[str, Any], exc: Exception, attempts: int) -> dict[str, Any]:
    retryable = _is_retryable_eval_error(exc)
    return {
        "id": case["id"],
        "type": case["type"],
        "passed": False,
        "skipped": retryable,
        "reason": f"Eval case raised after {attempts} attempt(s): {_truncate(str(exc), 500)}",
        "exception_type": exc.__class__.__name__,
        "transient_error": retryable,
    }


def _is_retryable_eval_error(exc: Exception) -> bool:
    if isinstance(exc, RetryableEvalError):
        return True
    try:
        from jee_tutor.agent.rate_limit import is_retryable_gemini_error

        return is_retryable_gemini_error(exc)
    except Exception:
        return False


def _retryable_response_error_reason(response: dict[str, Any]) -> str | None:
    if "error" not in response:
        return None

    details = response.get("details", [])
    text = " ".join([str(response.get("error", "")), *(str(detail) for detail in details)])
    try:
        from jee_tutor.agent.rate_limit import is_retryable_gemini_error

        if is_retryable_gemini_error(RuntimeError(text)):
            if response.get("error") == TUTOR_WORKFLOW_FAILURE_ERROR:
                return (
                    "Tutor invocation workflow failed before producing analysis: "
                    f"{_truncate(text, 500)}"
                )
            return f"Tutor invocation returned retryable error response: {_truncate(text, 500)}"
    except Exception:
        return None
    return None


def _enforce_eval_gate(*, score: float, min_score: float, skipped: int) -> None:
    if skipped:
        raise SystemExit(f"Agent eval run skipped {skipped} case(s); all cases must be scored.")
    if score < min_score:
        raise SystemExit(f"Agent eval score {score:.2f} is below required {min_score:.2f}")


def _redacted_response(response: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(response)
    if "analysis" in redacted:
        redacted["analysis"] = _truncate(str(redacted["analysis"]))
    if "details" in redacted:
        redacted["details"] = [_truncate(str(detail)) for detail in redacted["details"]]
    return redacted


def _truncate(value: str, limit: int = 1000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


def _print_failed_case_summary(results: list[dict[str, Any]]) -> None:
    for result in results:
        if result.get("passed"):
            continue
        status = "skipped" if result.get("skipped") else "failed"
        reason = _truncate(str(result.get("reason") or "No reason provided."), 500)
        print(f"eval_case_{status} id={result.get('id')} type={result.get('type')} reason={reason}")


def _publish_langfuse_summary(report: dict[str, Any]) -> None:
    try:
        from jee_tutor.agent.observability import EvaluationScore, LangfuseObservability

        passed = int(report["passed"])
        total = int(report.get("scored_total", report["total"]))
        skipped = int(report.get("skipped", 0))
        min_score = float(report["min_score"])
        score = float(report["score"])
        publish_payload = {
            "score": score,
            "passed": passed,
            "total": total,
            "skipped": skipped,
            "min_score": min_score,
            "pass": score >= min_score,
            "commit_sha": os.getenv("GITHUB_SHA"),
            "run_id": os.getenv("GITHUB_RUN_ID"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
            "ref_name": os.getenv("GITHUB_REF_NAME"),
        }
        publish_payload = {
            key: value for key, value in publish_payload.items() if value is not None
        }
        LangfuseObservability().publish_deploy_summary(
            name="cd-agent-evals",
            input_payload={
                "commit_sha": os.getenv("GITHUB_SHA"),
                "run_id": os.getenv("GITHUB_RUN_ID"),
            },
            output_payload=publish_payload,
            scores=[
                EvaluationScore(
                    name="cd_agent_eval_score",
                    value=score,
                    data_type="NUMERIC",
                    comment=f"{passed}/{total} scored eval cases passed, {skipped} skipped",
                ),
                EvaluationScore(
                    name="cd_agent_eval_pass",
                    value=score >= min_score,
                    data_type="BOOLEAN",
                    comment=f"Required minimum score: {min_score:.2f}",
                ),
            ],
            metadata=publish_payload,
            tags=["cd", "agent-evals"],
        )
    except Exception as exc:
        print(f"langfuse_eval_publish_error={exc}")


if __name__ == "__main__":
    main()
