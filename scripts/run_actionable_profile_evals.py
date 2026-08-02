from __future__ import annotations

import argparse
import json
from pathlib import Path


FORBIDDEN_STUDENT_TERMS = (
    "incomplete solution-space coverage",
    "reasoning is inferred",
    "evidence_id",
    "confidence",
    "be careful",
    "revise more",
)


def evaluate(document: dict) -> dict:
    failures: list[str] = []
    inventory = document.get("source_inventory", {})
    if inventory.get("structured_reports") != 18:
        failures.append("inventory_must_cover_18_reports")
    if inventory.get("matching_manual_embeddings") != 105:
        failures.append("inventory_must_cover_105_manual_embeddings")
    cases = document.get("cases", [])
    supported = [case for case in cases if case.get("supported")]
    if {case.get("subject") for case in supported} != {"Maths", "Physics", "Chemistry"}:
        failures.append("all_subjects_not_covered")
    for case in cases:
        case_id = case.get("id", "unknown")
        if case.get("supported"):
            if case.get("independent_questions", 0) < 2:
                failures.append(f"{case_id}:not_recurring")
            for field in ("heading", "do", "ask_this_when_you_see"):
                if not str(case.get(field, "")).strip():
                    failures.append(f"{case_id}:{field}_missing")
            if not str(case.get("heading", "")).strip().endswith("?"):
                failures.append(f"{case_id}:heading_not_self_question")
            visible = " ".join(str(case.get(key, "")) for key in ("heading", "do", "ask_this_when_you_see")).casefold()
            for term in FORBIDDEN_STUDENT_TERMS:
                if term in visible:
                    failures.append(f"{case_id}:forbidden_student_language:{term}")
        elif not case.get("rejection_reason"):
            failures.append(f"{case_id}:rejection_reason_missing")
    return {
        "schema_version": document.get("schema_version"),
        "gate_passed": not failures,
        "case_count": len(cases),
        "supported_case_count": len(supported),
        "source_inventory": inventory,
        "failed_assertions": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(args.cases.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
