import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "destroy_terraform_resources.sh"


class DestroyTerraformResourcesTest(unittest.TestCase):
    def run_script(self, apply_mode: str, state: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            calls_file = temp_path / "calls.log"
            apply_count_file = temp_path / "apply-count"
            terraform = temp_path / "terraform"
            terraform.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    printf '%s\\n' "$*" >> "$CALLS_FILE"
                    if [[ "$1 $2" == "state list" ]]; then
                      printf '%s\\n' "$FAKE_TERRAFORM_STATE"
                      exit 0
                    fi
                    if [[ "$1" == "plan" ]]; then
                      exit 0
                    fi
                    if [[ "$1" == "apply" ]]; then
                      count=0
                      if [[ -f "$APPLY_COUNT_FILE" ]]; then
                        count="$(<"$APPLY_COUNT_FILE")"
                      fi
                      count=$((count + 1))
                      printf '%s' "$count" > "$APPLY_COUNT_FILE"

                      if [[ "$FAKE_APPLY_MODE" == "transient_once" && "$count" -eq 1 ]]; then
                        echo "ErrorCode: NotStabilized"
                        exit 1
                      fi
                      if [[ "$FAKE_APPLY_MODE" == "permanent" ]]; then
                        echo "Error: AccessDenied"
                        exit 1
                      fi
                      exit 0
                    fi
                    exit 2
                    """
                )
            )
            terraform.chmod(0o755)

            sleep = temp_path / "sleep"
            sleep.write_text(
                "#!/usr/bin/env bash\nprintf 'sleep %s\\n' \"$1\" >> \"$CALLS_FILE\"\n"
            )
            sleep.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{temp_path}:{env['PATH']}",
                    "CALLS_FILE": str(calls_file),
                    "APPLY_COUNT_FILE": str(apply_count_file),
                    "FAKE_APPLY_MODE": apply_mode,
                    "FAKE_TERRAFORM_STATE": state,
                    "RUNNER_TEMP": str(temp_path),
                    "TERRAFORM_DESTROY_RETRY_DELAY_SECONDS": "0",
                }
            )
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                cwd=temp_path,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            result.calls = calls_file.read_text().splitlines()
            return result

    def test_replans_and_retries_after_not_stabilized(self):
        result = self.run_script(
            "transient_once",
            "\n".join(
                [
                    "aws_dynamodb_table.invocation_status",
                    "awscc_bedrockagentcore_runtime.tutor",
                    "aws_iam_role.agentcore_runtime",
                ]
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.calls.count("state list"), 2)
        self.assertEqual(
            sum(call.startswith("plan -destroy ") for call in result.calls),
            2,
        )
        self.assertEqual(
            result.calls.count("apply -auto-approve tfdestroy.plan"),
            2,
        )
        self.assertIn("sleep 0", result.calls)
        self.assertTrue(
            all("aws_dynamodb_table.invocation_status" not in call for call in result.calls)
        )

    def test_does_not_retry_a_permanent_error(self):
        result = self.run_script("permanent", "aws_iam_role.agentcore_runtime")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.calls.count("state list"), 1)
        self.assertEqual(
            result.calls.count("apply -auto-approve tfdestroy.plan"),
            1,
        )
        self.assertNotIn("sleep 0", result.calls)

    def test_succeeds_without_a_plan_when_only_tables_remain(self):
        result = self.run_script("success", "aws_dynamodb_table.invocation_status")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.calls, ["state list"])


if __name__ == "__main__":
    unittest.main()
