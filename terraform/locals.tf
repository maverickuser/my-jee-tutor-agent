locals {
  ecr_repo_name                = "${var.project_name}-repo"
  agentcore_runtime_name       = substr("JeeTutorAgent_${replace(var.project_name, "/[^a-zA-Z0-9_]/", "_")}", 0, 48)
  agentcore_endpoint_name      = "DEFAULT"
  email_delivery_function_name = substr("${var.project_name}-email-delivery", 0, 64)
  invocation_status_table_name = "${var.project_name}-invocations"
  student_diagnosis_metadata_table_name = "${var.project_name}-student-diagnosis-metadata"
  evidence_embedding_table_name = "${var.project_name}-evidence-embeddings"
  email_body_template_compact  = replace(replace(trimspace(var.email_body_template), "\n", " "), "\r", " ")

  curriculum_taxonomy_s3_path    = var.curriculum_taxonomy_s3_uri != "" ? trimprefix(var.curriculum_taxonomy_s3_uri, "s3://") : ""
  curriculum_taxonomy_s3_parts   = local.curriculum_taxonomy_s3_path != "" ? split("/", local.curriculum_taxonomy_s3_path) : []
  curriculum_taxonomy_s3_bucket  = length(local.curriculum_taxonomy_s3_parts) > 0 ? local.curriculum_taxonomy_s3_parts[0] : ""
  curriculum_taxonomy_s3_key     = length(local.curriculum_taxonomy_s3_parts) > 1 ? join("/", slice(local.curriculum_taxonomy_s3_parts, 1, length(local.curriculum_taxonomy_s3_parts))) : ""
  curriculum_taxonomy_object_arn = local.curriculum_taxonomy_s3_bucket != "" && local.curriculum_taxonomy_s3_key != "" ? "arn:aws:s3:::${local.curriculum_taxonomy_s3_bucket}/${local.curriculum_taxonomy_s3_key}" : ""

  # Use created guardrail if not overridden via var.bedrock_guardrail_id.
  bedrock_guardrail_id = var.bedrock_guardrail_id != "" ? var.bedrock_guardrail_id : try(awscc_bedrock_guardrail.jee_tutor[0].guardrail_id, "")
}
