locals {
  ecr_repo_name                = "${var.project_name}-repo"
  agentcore_runtime_name       = substr("JeeTutorAgent_${replace(var.project_name, "/[^a-zA-Z0-9_]/", "_")}", 0, 48)
  agentcore_endpoint_name      = "DEFAULT"
  email_delivery_function_name = substr("${var.project_name}-email-delivery", 0, 64)
  email_body_template_compact  = replace(replace(trimspace(var.email_body_template), "\n", " "), "\r", " ")

  # Use created guardrail if not overridden via var.bedrock_guardrail_id.
  bedrock_guardrail_id = var.bedrock_guardrail_id != "" ? var.bedrock_guardrail_id : try(awscc_bedrock_guardrail.jee_tutor[0].guardrail_id, "")
}
