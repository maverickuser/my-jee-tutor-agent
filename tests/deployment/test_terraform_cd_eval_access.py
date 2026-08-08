import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class TerraformCdEvalAccessTest(unittest.TestCase):
    def test_runtime_role_access_is_limited_to_cd_image_prefixes(self):
        terraform = "\n".join(
            path.read_text()
            for path in sorted((REPO_ROOT / "terraform").glob("*.tf"))
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
        self.assertIn(
            "${CD_EVAL_IMAGE_S3_PREFIX:-s3://${TF_STATE_BUCKET}/cd-evals-images/}",
            workflow,
        )
        self.assertIn("--expected-image-count 3", workflow)
        self.assertIn("scripts/run_agentcore_profile_smoke.py", workflow)
        self.assertIn("student_diagnosis_metadata_table_name", workflow)
        self.assertIn("evidence_embedding_table_name", workflow)
        self.assertIn("poetry run python scripts/run_crewai_react_evals.py", workflow)

    def test_optional_cd_quality_jobs_are_disabled_by_default(self):
        workflow = (REPO_ROOT / ".github/workflows/cd.yml").read_text()

        variables = [
            "REACT_DIAGNOSIS_EVALS_ENABLED",
            "DEPLOYED_RUNTIME_SMOKE_ENABLED",
            "AGENT_EVALS_ENABLED",
            "GARAK_SCAN_ENABLED",
        ]
        for variable in variables:
            self.assertIn(f"{variable}: ${{{{ vars.{variable} || 'false' }}}}", workflow)
            self.assertIn(f"vars.{variable} == 'true'", workflow)

        self.assertNotIn("Mandatory ReAct Diagnosis Evals", workflow)
        self.assertIn("needs.react_diagnosis_evals.result == 'skipped'", workflow)

    def test_cd_workflow_uploads_curriculum_taxonomy_before_runtime_deploy(self):
        workflow = (REPO_ROOT / ".github/workflows/cd.yml").read_text()

        self.assertIn("prepare_curriculum_taxonomy:", workflow)
        self.assertIn("scripts/publish_curriculum_taxonomy.py", workflow)
        self.assertIn("--taxonomy-file knowledge/jee_curriculum_taxonomy.json", workflow)
        self.assertIn('--s3-uri "$CURRICULUM_TAXONOMY_S3_URI"', workflow)
        self.assertIn("curriculum-publish-report", workflow)
        self.assertIn("prepare_curriculum_taxonomy", workflow)
        self.assertIn(
            "format('s3://{0}/curriculum/jee_curriculum_taxonomy.json', "
            "vars.TF_STATE_BUCKET || 'jee-tutor-agent-terraform-state')",
            workflow,
        )
        self.assertIn(
            "TF_VAR_curriculum_taxonomy_s3_uri: ${{ env.CURRICULUM_TAXONOMY_S3_URI }}",
            workflow,
        )

    def test_cd_workflow_uploads_chapter_weightage_before_runtime_deploy(self):
        workflow = (REPO_ROOT / ".github/workflows/cd.yml").read_text()

        self.assertIn("scripts/publish_chapter_weightage.py", workflow)
        self.assertIn("--source-dir knowledge/chapter_weightage", workflow)
        self.assertIn('--bucket "$CHAPTER_WEIGHTAGE_S3_BUCKET"', workflow)
        self.assertIn('--prefix "$CHAPTER_WEIGHTAGE_S3_PREFIX"', workflow)
        self.assertIn("knowledge/chapter_weightage/*.json", workflow)
        self.assertIn("eval_runs/chapter-weightage-publish.json", workflow)
        self.assertIn(
            "CHAPTER_WEIGHTAGE_S3_PREFIX: ${{ "
            "vars.CHAPTER_WEIGHTAGE_S3_PREFIX || "
            "'curriculum/chapter-weightage' }}",
            workflow,
        )

    def test_runtime_receives_curriculum_taxonomy_env_and_read_access(self):
        terraform = "\n".join(
            path.read_text()
            for path in sorted((REPO_ROOT / "terraform").glob("*.tf"))
        )

        self.assertIn("variable \"curriculum_taxonomy_s3_uri\"", terraform)
        self.assertIn("CURRICULUM_TAXONOMY_S3_URI", terraform)
        self.assertIn("CURRICULUM_TAXONOMY_REQUIRED", terraform)
        self.assertIn("CURRICULUM_TAXONOMY_CACHE_TTL_SECONDS", terraform)
        self.assertIn("S3CurriculumTaxonomyRead", terraform)
        self.assertIn("local.curriculum_taxonomy_object_arn", terraform)
        self.assertIn(
            "s3://jee-tutor-agent-terraform-state/curriculum/jee_curriculum_taxonomy.json",
            terraform,
        )

    def test_runtime_receives_student_diagnosis_metadata_table_and_permissions(self):
        terraform = "\n".join(
            path.read_text()
            for path in sorted((REPO_ROOT / "terraform").glob("*.tf"))
        )

        self.assertIn("aws_dynamodb_table\" \"student_diagnosis_metadata", terraform)
        self.assertIn("STUDENT_DIAGNOSIS_METADATA_ENABLED", terraform)
        self.assertIn("STUDENT_DIAGNOSIS_METADATA_TABLE_NAME", terraform)
        self.assertIn("ReadWriteStudentDiagnosisMetadata", terraform)
        self.assertIn("dynamodb:Query", terraform)
        self.assertIn("student_diagnosis_metadata_table_name", terraform)

    def test_runtime_receives_evidence_embedding_table_and_permissions(self):
        terraform = "\n".join(
            path.read_text()
            for path in sorted((REPO_ROOT / "terraform").glob("*.tf"))
        )

        self.assertIn("aws_dynamodb_table\" \"evidence_embeddings", terraform)
        self.assertIn("EVIDENCE_EMBEDDING_ENABLED", terraform)
        self.assertIn("EVIDENCE_EMBEDDING_TABLE_NAME", terraform)
        self.assertIn("ReadWriteEvidenceEmbeddings", terraform)
        self.assertIn("evidence_embedding_table_name", terraform)

    def test_runtime_and_cd_use_the_exact_profile_model_matrix(self):
        terraform = "\n".join(
            path.read_text()
            for path in sorted((REPO_ROOT / "terraform").glob("*.tf"))
        )
        workflow = (REPO_ROOT / ".github/workflows/cd.yml").read_text()

        for name in [
            "live_generation_model",
            "live_embedding_model",
            "cd_generation_model",
            "cd_embedding_model",
            "profile_report_s3_bucket_name",
            "profile_report_s3_bucket_create",
            "profile_report_s3_prefix",
            "structured_diagnosis_enabled",
        ]:
            self.assertIn(f'variable "{name}"', terraform)
            self.assertIn(f"TF_VAR_{name}", workflow)

        for env_name in [
            "LIVE_GENERATION_MODEL",
            "LIVE_EMBEDDING_MODEL",
            "CD_GENERATION_MODEL",
            "CD_EMBEDDING_MODEL",
            "PROFILE_REPORT_S3_BUCKET",
            "PROFILE_REPORT_S3_PREFIX",
            "STRUCTURED_DIAGNOSIS_ENABLED",
        ]:
            self.assertIn(env_name, terraform)
            self.assertIn(env_name, workflow)

        self.assertIn("gemini/gemini-2.5-flash-lite", workflow)
        self.assertIn("gemini/gemini-embedding-001", workflow)
        self.assertIn("gemini/gemini-3.6-flash", workflow)
        self.assertIn("gemini/gemini-embedding-2", workflow)
        self.assertIn("PROFILE_REPORT_S3_PREFIX", workflow)
        self.assertIn("WriteProfileReportArtifacts", terraform)
        self.assertIn("S3ChapterWeightageRead", terraform)
        self.assertIn("scripts/run_actionable_profile_evals.py", workflow)
        self.assertIn("actionable-profile-evals.json", workflow)
        self.assertIn('aws_s3_bucket" "profile_reports', terraform)
        self.assertIn("profile_report_s3_bucket_name", terraform)
        self.assertIn('TF_VAR_profile_report_s3_bucket_create: "false"', workflow)
        self.assertNotIn("openai/gpt-4o", workflow)
        self.assertNotIn("CD_EVAL_VISION_MODEL", workflow)
        self.assertNotIn("CD_EVAL_CREWAI_MODEL", workflow)

    def test_cd_profile_headers_secret_and_lifecycle_warning_are_deployed(self):
        terraform = "\n".join(
            path.read_text()
            for path in sorted((REPO_ROOT / "terraform").glob("*.tf"))
        )
        workflow = (REPO_ROOT / ".github/workflows/cd.yml").read_text()

        for header in [
            "X-JEE-Execution-Profile",
            "X-JEE-CD-Timestamp",
            "X-JEE-CD-Run-ID",
            "X-JEE-CD-Signature",
        ]:
            self.assertIn(header, terraform)
        self.assertIn("request_header_allowlist", terraform)
        self.assertIn("ReadCdExecutionHmacKey", terraform)
        self.assertIn("secretsmanager:GetSecretValue", terraform)
        self.assertIn("CD_EXECUTION_HMAC_SECRET_ARN", terraform)
        self.assertIn("Provision CD execution HMAC secret", workflow)
        self.assertIn("CD_EXECUTION_HMAC_SECRET", workflow)
        self.assertEqual(workflow.count("--cd-execution-secret-id"), 2)
        self.assertIn("scripts/check_cd_model_lifecycle.py", workflow)


if __name__ == "__main__":
    unittest.main()
