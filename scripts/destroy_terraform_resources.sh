#!/usr/bin/env bash

set -uo pipefail

max_attempts="${TERRAFORM_DESTROY_MAX_ATTEMPTS:-3}"
retry_delay_seconds="${TERRAFORM_DESTROY_RETRY_DELAY_SECONDS:-60}"
plan_file="${TERRAFORM_DESTROY_PLAN_FILE:-tfdestroy.plan}"

if ! [[ "$max_attempts" =~ ^[1-9][0-9]*$ ]]; then
  echo "TERRAFORM_DESTROY_MAX_ATTEMPTS must be a positive integer." >&2
  exit 2
fi

if ! [[ "$retry_delay_seconds" =~ ^[0-9]+$ ]]; then
  echo "TERRAFORM_DESTROY_RETRY_DELAY_SECONDS must be a non-negative integer." >&2
  exit 2
fi

create_destroy_plan() {
  local state_output
  local resource
  local -a targets=()

  if ! state_output="$(terraform state list)"; then
    echo "Unable to list Terraform state while preparing the destroy plan." >&2
    return 2
  fi

  while IFS= read -r resource; do
    if [[ -z "$resource" ]]; then
      continue
    fi

    case "$resource" in
      *aws_dynamodb_table.*)
        echo "Preserving DynamoDB table in state: $resource"
        ;;
      *)
        targets+=("-target=$resource")
        ;;
    esac
  done <<< "$state_output"

  if [[ "${#targets[@]}" -eq 0 ]]; then
    echo "No destroyable Terraform resources found after excluding DynamoDB tables."
    return 1
  fi

  if ! terraform plan -destroy "${targets[@]}" -out="$plan_file"; then
    echo "Unable to create a fresh Terraform destroy plan." >&2
    return 2
  fi
}

create_destroy_plan
plan_status=$?
if [[ "$plan_status" -eq 1 ]]; then
  exit 0
fi
if [[ "$plan_status" -ne 0 ]]; then
  exit "$plan_status"
fi

for ((attempt = 1; attempt <= max_attempts; attempt++)); do
  apply_log="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/terraform-destroy-attempt-${attempt}.log"

  terraform apply -auto-approve "$plan_file" 2>&1 | tee "$apply_log"
  apply_status=${PIPESTATUS[0]}

  if [[ "$apply_status" -eq 0 ]]; then
    exit 0
  fi

  if ! grep -Eq 'ErrorCode: (NotStabilized|ResourceConflict)|ConcurrentOperation' "$apply_log"; then
    echo "Terraform destroy failed with a non-retryable error." >&2
    exit "$apply_status"
  fi

  if [[ "$attempt" -eq "$max_attempts" ]]; then
    echo "Terraform destroy still failed after $max_attempts attempts." >&2
    exit "$apply_status"
  fi

  echo "::warning::Terraform destroy hit a transient AWS stabilization error on attempt $attempt/$max_attempts. Retrying with a fresh plan after ${retry_delay_seconds}s."
  if ! sleep "$retry_delay_seconds"; then
    echo "Interrupted while waiting to retry Terraform destroy." >&2
    exit 1
  fi

  create_destroy_plan
  plan_status=$?
  if [[ "$plan_status" -eq 1 ]]; then
    exit 0
  fi
  if [[ "$plan_status" -ne 0 ]]; then
    exit "$plan_status"
  fi
done
