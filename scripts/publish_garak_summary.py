import argparse
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish aggregate garak deploy metrics.")
    parser.add_argument("--enabled", choices=["true", "false"], required=True)
    parser.add_argument("--probes", default="")
    parser.add_argument("--hit-threshold", type=int, default=0)
    parser.add_argument("--hit-count", type=int, default=0)
    parser.add_argument("--scan-outcome", default="success")
    parser.add_argument("--fail-on-threshold", action="store_true")
    args = parser.parse_args()

    enabled = args.enabled == "true"
    passed = (not enabled) or (
        args.scan_outcome == "success" and args.hit_count <= args.hit_threshold
    )
    payload = _summary_payload(
        enabled=enabled,
        probes=args.probes,
        hit_threshold=args.hit_threshold,
        hit_count=args.hit_count,
        scan_outcome=args.scan_outcome,
        passed=passed,
    )
    _publish_langfuse_summary(payload)

    print(
        "garak_summary="
        f"enabled={str(enabled).lower()} "
        f"hits={args.hit_count} "
        f"threshold={args.hit_threshold} "
        f"scan_outcome={args.scan_outcome} "
        f"pass={str(passed).lower()}"
    )
    if args.fail_on_threshold and enabled and not passed:
        raise SystemExit(
            f"garak found {args.hit_count} hit(s), above threshold {args.hit_threshold}"
        )


def _summary_payload(
    *,
    enabled: bool,
    probes: str,
    hit_threshold: int,
    hit_count: int,
    scan_outcome: str,
    passed: bool,
) -> dict[str, Any]:
    payload = {
        "enabled": enabled,
        "probes": probes,
        "hit_threshold": hit_threshold,
        "hit_count": hit_count,
        "scan_outcome": scan_outcome,
        "pass": passed,
        "commit_sha": os.getenv("GITHUB_SHA"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "ref_name": os.getenv("GITHUB_REF_NAME"),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _publish_langfuse_summary(payload: dict[str, Any]) -> None:
    try:
        from jee_tutor.adapters.langfuse import EvaluationScore, LangfuseObservability

        enabled = bool(payload["enabled"])
        hit_count = int(payload["hit_count"])
        hit_threshold = int(payload["hit_threshold"])
        passed = bool(payload["pass"])
        LangfuseObservability().publish_deploy_summary(
            name="cd-garak-scan",
            input_payload={
                "enabled": enabled,
                "probes": payload.get("probes"),
                "commit_sha": payload.get("commit_sha"),
                "run_id": payload.get("run_id"),
            },
            output_payload=payload,
            scores=[
                EvaluationScore(
                    name="cd_garak_enabled",
                    value=enabled,
                    data_type="BOOLEAN",
                ),
                EvaluationScore(
                    name="cd_garak_hit_count",
                    value=hit_count,
                    data_type="NUMERIC",
                    comment=f"Threshold: {hit_threshold}",
                ),
                EvaluationScore(
                    name="cd_garak_pass",
                    value=passed,
                    data_type="BOOLEAN",
                    comment=f"{hit_count} hit(s), threshold {hit_threshold}",
                ),
            ],
            metadata=payload,
            tags=["cd", "garak"],
        )
    except Exception as exc:
        print(f"langfuse_garak_publish_error={exc}")


if __name__ == "__main__":
    main()
