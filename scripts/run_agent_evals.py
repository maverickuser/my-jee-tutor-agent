import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CD evals for the JEE tutor agent.")
    parser.add_argument("--cases", default="evals/jee_tutor_eval_cases.json")
    parser.add_argument("--image-folder", default="tests/fixtures/image_folder")
    parser.add_argument("--output", default="eval_runs/agent-evals.json")
    parser.add_argument("--min-score", type=float, default=0.75)
    args = parser.parse_args()

    cases = _load_json(Path(args.cases))
    image_folder = str(Path(args.image_folder).resolve())
    results = [_run_case(case, image_folder) for case in cases]
    passed = sum(1 for result in results if result["passed"])
    score = passed / len(results) if results else 0.0

    report = {
        "score": score,
        "passed": passed,
        "total": len(results),
        "min_score": args.min_score,
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"agent_eval_score={score:.2f} ({passed}/{len(results)} passed)")
    if score < args.min_score:
        raise SystemExit(f"Agent eval score {score:.2f} is below required {args.min_score:.2f}")


def _load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_case(case: dict[str, Any], image_folder: str) -> dict[str, Any]:
    from agentcore_handler import handle_tutor_invocation

    payload = {
        "image_folder": image_folder,
        "question_context": case["question_context"],
        "metadata": {"source": "cd-evals", "eval_case_id": case["id"]},
        "tags": ["cd-evals", case["id"]],
    }
    response = handle_tutor_invocation(payload)

    if case["type"] == "analysis":
        return _score_analysis_case(case, response)
    if case["type"] == "guardrail":
        return _score_guardrail_case(case, response)

    return {
        "id": case["id"],
        "type": case["type"],
        "passed": False,
        "reason": f"Unsupported eval case type: {case['type']}",
        "response": _redacted_response(response),
    }


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


if __name__ == "__main__":
    main()
