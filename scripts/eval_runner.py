from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def run_strict_cases(
    cases: dict[str, Callable[[], dict[str, Any] | None]],
) -> dict[str, Any]:
    results = []
    for case_id, runner in cases.items():
        started = time.monotonic()
        try:
            details = runner() or {}
            passed = bool(details.pop("passed", True))
            result = {
                "case_id": case_id,
                "status": "passed" if passed else "failed",
                "passed": passed,
                **details,
            }
        except Exception as exc:
            result = {
                "case_id": case_id,
                "status": "error",
                "passed": False,
                "error_type": type(exc).__name__,
                "reason": (str(exc) or "[no message]")[:500],
            }
        result["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        results.append(result)
        _publish_case(result)
    return {
        "gate_passed": len(results) == len(cases) and all(item["passed"] for item in results),
        "case_count": len(results),
        "passed_count": sum(item["passed"] for item in results),
        "cases": results,
    }


def write_report(report: dict[str, Any], output: str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def _publish_case(result: dict[str, Any]) -> None:
    try:
        from jee_tutor.adapters.langfuse import EvaluationScore, LangfuseObservability

        metric_names = (
            "groundedness_score",
            "unsupported_claim_rate",
            "contradiction_rate",
            "completeness_score",
            "inference_quality_score",
        )
        scores = [
            EvaluationScore(
                name="case_assertion_passed",
                value=int(result["passed"]),
                data_type="BOOLEAN",
            )
        ]
        scores.extend(
            EvaluationScore(name=name, value=result[name], data_type="NUMERIC")
            for name in metric_names
            if isinstance(result.get(name), int | float)
        )
        LangfuseObservability().publish_deploy_summary(
            name=f"cd-quality-eval-{result['case_id'].lower()}",
            input_payload={"case_id": result["case_id"]},
            output_payload={
                key: value
                for key, value in result.items()
                if key
                not in {
                    "evidence_summary",
                    "raw_output",
                    "images",
                    "prompt",
                }
            },
            scores=scores,
            metadata={"case_id": result["case_id"], "status": result["status"]},
            tags=["cd", "quality-pipeline"],
        )
    except Exception as exc:
        print(
            f"langfuse_case_publish_failed case_id={result['case_id']} "
            f"error_type={type(exc).__name__}"
        )
