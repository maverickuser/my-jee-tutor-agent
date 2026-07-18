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
        self.assertIn("poetry run python scripts/run_crewai_react_evals.py", workflow)

    def test_cd_workflow_uploads_curriculum_taxonomy_before_runtime_deploy(self):
        workflow = (REPO_ROOT / ".github/workflows/cd.yml").read_text()

        self.assertIn("prepare_curriculum_taxonomy:", workflow)
        self.assertIn("scripts/publish_curriculum_taxonomy.py", workflow)
        self.assertIn("--taxonomy-file knowledge/jee_curriculum_taxonomy.json", workflow)
        self.assertIn('--s3-uri "$CURRICULUM_TAXONOMY_S3_URI"', workflow)
        self.assertIn("curriculum-taxonomy-publish-report", workflow)
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

    def test_runtime_and_cd_evals_can_override_models(self):
        terraform = "\n".join(
            path.read_text()
            for path in sorted((REPO_ROOT / "terraform").glob("*.tf"))
        )
        workflow = (REPO_ROOT / ".github/workflows/cd.yml").read_text()

        for name in [
            "vision_model",
            "crewai_model",
            "profile_report_model",
            "profile_embedding_model",
            "profile_semantic_cluster_model",
            "structured_diagnosis_enabled",
            "profile_report_llm_enabled",
        ]:
            self.assertIn(f'variable "{name}"', terraform)
            self.assertIn(f"TF_VAR_{name}", workflow)

        for env_name in [
            "VISION_MODEL",
            "CREWAI_MODEL",
            "PROFILE_REPORT_MODEL",
            "PROFILE_EMBEDDING_MODEL",
            "PROFILE_SEMANTIC_CLUSTER_MODEL",
            "STRUCTURED_DIAGNOSIS_ENABLED",
            "PROFILE_REPORT_LLM_ENABLED",
        ]:
            self.assertIn(env_name, terraform)
            self.assertIn(env_name, workflow)

        self.assertIn("CD_EVAL_CREWAI_MODEL", workflow)
        self.assertIn("CD_EVAL_VISION_MODEL", workflow)
        self.assertIn("secrets.OPENAI_API_KEY != '' && 'openai/gpt-4o'", workflow)
        self.assertIn(
            "CD_EVAL_STRUCTURED_DIAGNOSIS_ENABLED || "
            "(secrets.OPENAI_API_KEY != '' && 'false'",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
