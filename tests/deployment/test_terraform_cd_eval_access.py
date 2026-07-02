import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class TerraformCdEvalAccessTest(unittest.TestCase):
    def test_runtime_role_access_is_limited_to_cd_image_prefixes(self):
        terraform = (REPO_ROOT / "terraform/main.tf").read_text()

        self.assertIn(
            '"arn:aws:s3:::${var.cd_eval_bucket_name}/cd-final-evaluator/*"',
            terraform,
        )
        self.assertIn(
            '"arn:aws:s3:::${var.cd_eval_bucket_name}/cd-evals-images/*"',
            terraform,
        )
        self.assertIn('"s3:prefix"', terraform)
        self.assertNotIn(
            '"arn:aws:s3:::${var.cd_eval_bucket_name}/*"',
            terraform,
        )

    def test_cd_workflow_always_passes_eval_bucket_name(self):
        workflow = (REPO_ROOT / ".github/workflows/cd.yml").read_text()

        self.assertEqual(
            workflow.count("TF_VAR_cd_eval_bucket_name: ${{ env.TF_STATE_BUCKET }}"),
            2,
        )


if __name__ == "__main__":
    unittest.main()
