# Diagnosis Quality Pipeline Operations

## Runtime controls

`src/config/llm.toml` enables structured diagnosis, constrained ReAct, and the
sampled final evaluator. Rollback controls are:

- `react_diagnosis.enabled = false`: use the direct single-tool path.
- `final_evaluator.mode = "shadow"`: evaluate sampled requests without gating.
- `final_evaluator.mode = "disabled"` or `enabled = false`: disable evaluation.
- `final_evaluator.sample_rate`: stable sampling from `0.0` through `1.0`.

CD always runs all ten `REACT-*` cases, all ten `EVAL-*` cases, and the deployed
runtime smoke. A failed, errored, or missing case fails the job; aggregate scores
do not override individual failures.

## Calibration and rollout

Before changing thresholds, collect a versioned human-reviewed set containing
grounded, unsupported, contradicted, incomplete, qualified-inference,
unreadable, and prompt-injection examples. Record reviewer labels, diagnosis
schema version, evaluator model, thresholds, false-pass rate, false-reject rate,
and p50/p95/p99 diagnosis and evaluation latency. Threshold changes require an
owner-approved calibration report. Shadow results cannot block responses.

## New Relic operations

The application sends structured logs directly to the New Relic Log API. It
does not use a CloudWatch subscription or forwarding Lambda. CloudWatch remains
the fallback sink.

Useful NRQL:

```sql
SELECT count(*) FROM Log FACET terminal_outcome SINCE 1 hour ago
SELECT count(*) FROM Log FACET workflow_stage, severity SINCE 1 hour ago
SELECT count(*) FROM Log WHERE message LIKE '%final_evaluator_decision%' FACET message
SELECT count(*) FROM Log WHERE message LIKE '%new_relic_log_%' SINCE 1 hour ago
```

Alert on sustained delivery failures, queue-full warnings, any dropped records,
and absence of production logs for 15 minutes. The service owner owns the
dashboard and alerts; platform security owns secret access and retention.

To rotate the key, update the GitHub Actions `NEW_RELIC_LICENSE_KEY` secret and
run CD. CD writes a new Secrets Manager secret version without printing the key.
Restart/redeploy the runtime so startup resolves the new version. If delivery
fails, verify the secret ARN permission, region (`US` or `EU`), egress, and New
Relic response status in CloudWatch.

New Relic retention and access must follow the production account policy.
Logs must not contain images, prompts, completions, credentials, signed URLs, or
student identity. Automated canary querying requires a separate least-privilege
query key and account ID; the ingest license key cannot query logs.
